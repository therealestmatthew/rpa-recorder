"""`LLMClassifier` — orchestrates one LLM-tier classification.

Flow per call:
1. Build messages + tools via `PromptStrategy`.
2. Compute cache key from `model + prompt.version + signature(...)`.
3. Hit cache → parse and return (no API call, no audit row).
4. Else: budget guard → semaphore → backend (with retry) → parse.
5. Persist in parallel via `asyncio.TaskGroup`: bronze blob, silver
   `LLMCallRow`, cache set, budget increment.
6. Return the candidate (None if parser abstained — audit row + bronze
   are still written).

Persistence task bodies catch their own exceptions so a bronze failure
doesn't cascade into the silver write or the return value. The classifier
never raises on a persistence failure — only on retried-out backend
failures or `LLMBudgetExceeded`.
"""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime
from time import perf_counter
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import structlog

from .concurrency import make_semaphore
from .cost import compute_cost
from .protocol import LLMBudgetExceeded

if TYPE_CHECKING:
    from collections.abc import Callable
    from contextlib import AbstractAsyncContextManager

    from sqlalchemy.ext.asyncio import AsyncSession

    from rpa_recorder.classifier.heuristic.protocol import ClassifyCandidate
    from rpa_recorder.medallion import BronzeWriter
    from rpa_recorder.models import RecordedAction

    from .cost import BudgetGuard
    from .protocol import (
        LLMBackend,
        LLMResponse,
        PromptStrategy,
        ResponseCache,
        ResponseParser,
        RetryPolicy,
    )

_log = structlog.get_logger(__name__)

_DEFAULT_MAX_TOKENS: int = 512


def _retryable_types() -> tuple[type[BaseException], ...]:
    """Compute retryable exception types lazily so anthropic stays optional in tests."""
    from anthropic import APIStatusError, APITimeoutError, RateLimitError  # noqa: PLC0415

    return (RateLimitError, APIStatusError, APITimeoutError, asyncio.TimeoutError)


class LLMClassifier:
    """One-shot orchestrator: prompt → backend → parser → persist."""

    def __init__(
        self,
        *,
        backend: LLMBackend,
        prompt: PromptStrategy,
        parser: ResponseParser,
        retry: RetryPolicy,
        cache: ResponseCache | None = None,
        cache_ttl_s: int = 86400,
        semaphore: asyncio.Semaphore | None = None,
        max_concurrency: int = 5,
        bronze: BronzeWriter | None = None,
        session_factory: Callable[[], AbstractAsyncContextManager[AsyncSession]] | None = None,
        budget: BudgetGuard | None = None,
        request_timeout_s: float = 60.0,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
        retryable: tuple[type[BaseException], ...] | None = None,
    ) -> None:
        self._backend = backend
        self._prompt = prompt
        self._parser = parser
        self._retry = retry
        self._cache = cache
        self._cache_ttl_s = cache_ttl_s
        self._semaphore = semaphore if semaphore is not None else make_semaphore(max_concurrency)
        self._bronze = bronze
        self._session_factory = session_factory
        self._budget = budget
        self._timeout_s = request_timeout_s
        self._max_tokens = max_tokens
        self._retryable = retryable

    @property
    def semaphore(self) -> asyncio.Semaphore:
        """Exposed so `Classifier.classify_batch` can introspect/share if needed."""
        return self._semaphore

    def _cache_key(self, action: RecordedAction, surrounding: list[RecordedAction]) -> str:
        seed = f"{self._backend.model}|{self._prompt.version}|{self._prompt.signature(action, surrounding)}"
        return hashlib.sha256(seed.encode("utf-8")).hexdigest()

    async def classify(
        self,
        action: RecordedAction,
        surrounding: list[RecordedAction],
    ) -> ClassifyCandidate | None:
        """Classify one action. Returns None when the parser abstains or the budget is exceeded.

        Raises only on backend failures that survived the retry policy (or
        on programmer error). Per-persistence-task failures log but never
        propagate.
        """
        messages, tools = self._prompt.build(action, surrounding)
        key = self._cache_key(action, surrounding)

        if self._cache is not None:
            cached = await self._cache.get(key)
            if cached is not None:
                _log.debug("llm_cache_hit", key=key, model=self._backend.model)
                return self._parser.parse(cached)

        if self._budget is not None:
            await self._budget.check_or_raise()

        retryable = self._retryable if self._retryable is not None else _retryable_types()

        async with self._semaphore:
            started = perf_counter()
            response = await self._retry.execute(
                lambda: self._backend.complete(
                    messages,
                    max_tokens=self._max_tokens,
                    temperature=0.0,
                    timeout_s=self._timeout_s,
                    tools=tools,
                ),
                retryable=retryable,
            )
            latency_ms = int((perf_counter() - started) * 1000)

        candidate = self._parser.parse(response)
        if candidate is None:
            _log.warning(
                "llm_parse_abstain",
                model=self._backend.model,
                stop_reason=response.stop_reason,
            )

        await self._persist(
            action=action,
            messages=messages,
            response=response,
            cache_key=key,
            latency_ms=latency_ms,
        )
        return candidate

    async def _persist(
        self,
        *,
        action: RecordedAction,
        messages: list[dict[str, Any]],
        response: LLMResponse,
        cache_key: str,
        latency_ms: int,
    ) -> None:
        call_id = uuid4()
        cost_usd = compute_cost(self._backend.model, response.input_tokens, response.output_tokens)

        async def write_bronze() -> None:
            if self._bronze is None:
                return
            try:
                await self._bronze.write_llm_call(
                    call_id,
                    {"prompt": messages, "response": response.raw, "model": self._backend.model},
                )
            except Exception as exc:
                _log.error("llm_bronze_write_failed", call_id=str(call_id), error=str(exc))

        async def write_silver() -> None:
            if self._session_factory is None:
                return
            try:
                from rpa_recorder.storage.db import LLMCallRow  # noqa: PLC0415

                row = LLMCallRow(
                    id=str(call_id),
                    called_for="classify",
                    model=self._backend.model,
                    prompt=_truncate(_messages_to_text(messages)),
                    response=_truncate(response.text or _tool_calls_to_text(response.tool_calls)),
                    action_id=str(action.id),
                    input_tokens=response.input_tokens,
                    output_tokens=response.output_tokens,
                    latency_ms=latency_ms,
                    created_at=datetime.now(UTC),
                )
                async with self._session_factory() as session:
                    session.add(row)
                    await session.flush()
            except Exception as exc:
                _log.error("llm_silver_write_failed", call_id=str(call_id), error=str(exc))

        async def set_cache() -> None:
            if self._cache is None:
                return
            try:
                await self._cache.set(cache_key, response, self._cache_ttl_s)
            except Exception as exc:
                _log.error("llm_cache_set_failed", key=cache_key, error=str(exc))

        async def record_budget() -> None:
            if self._budget is None:
                return
            try:
                await self._budget.record_spend(cost_usd)
            except Exception as exc:
                _log.error("llm_budget_record_failed", error=str(exc))

        async with asyncio.TaskGroup() as tg:
            tg.create_task(write_bronze())
            tg.create_task(write_silver())
            tg.create_task(set_cache())
            tg.create_task(record_budget())


_PROMPT_TRUNCATE = 8000


def _truncate(text: str) -> str:
    if len(text) <= _PROMPT_TRUNCATE:
        return text
    return text[:_PROMPT_TRUNCATE] + "…[truncated]"


def _messages_to_text(messages: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if isinstance(content, list):
            content = " ".join(str(c) for c in content)
        parts.append(f"[{role}] {content}")
    return "\n".join(parts)


def _tool_calls_to_text(tool_calls: list[dict[str, Any]]) -> str:
    if not tool_calls:
        return ""
    return " | ".join(f"{c.get('name', '?')}({c.get('input', {})})" for c in tool_calls)


__all__ = ["LLMBudgetExceeded", "LLMClassifier"]
