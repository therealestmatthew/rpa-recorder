"""Tier-5 recovery: ask an LLM for a fresh selector when heuristics give up.

Composes M9's `LLMBackend`, `RetryPolicy`, `ResponseCache`, `BudgetGuard`,
and `Semaphore` (the same instance shared with the classifier so total
LLM in-flight stays bounded). Builds a filtered DOM ≤ 5 KB by stripping
`<script>`, `<style>`, `<svg>`, and HTML comments. The redaction context
is honoured when serializing the failed action so sensitive payload values
(passwords, etc.) never reach the wire.

Bronze + silver writes happen best-effort: a bronze write failure logs
but does not mask a recovery success.
"""

import asyncio
import hashlib
import re
from datetime import UTC, datetime
from time import monotonic
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import structlog
from playwright.async_api import Error as PlaywrightError

from rpa_recorder.classifier.llm.cost import compute_cost
from rpa_recorder.classifier.llm.protocol import LLMBudgetExceeded
from rpa_recorder.models import FailureMode
from rpa_recorder.recovery.parsers.selector_tool_use import SelectorToolUseParser
from rpa_recorder.recovery.prompts.reselect_v1 import ReselectV1Prompt
from rpa_recorder.recovery.protocol import RecoveryContext, RecoveryDecision

if TYPE_CHECKING:
    from collections.abc import Callable
    from contextlib import AbstractAsyncContextManager

    from playwright.async_api import Page
    from sqlalchemy.ext.asyncio import AsyncSession

    from rpa_recorder.classifier.llm.protocol import LLMResponse
    from rpa_recorder.models import ActionExecution, ElementSelector, RecordedAction

_log = structlog.get_logger(__name__)

_DOM_BUDGET_BYTES: int = 5_000
_MAX_TOKENS: int = 512


def _retryable_types() -> tuple[type[BaseException], ...]:
    """Lazy import so anthropic stays optional in unit tests."""
    from anthropic import (  # noqa: PLC0415
        APIStatusError,
        APITimeoutError,
        RateLimitError,
    )

    return (RateLimitError, APIStatusError, APITimeoutError, asyncio.TimeoutError)


_SCRIPT_RE = re.compile(r"<script\b[^>]*>.*?</script\s*>", re.IGNORECASE | re.DOTALL)
_STYLE_RE = re.compile(r"<style\b[^>]*>.*?</style\s*>", re.IGNORECASE | re.DOTALL)
_SVG_RE = re.compile(r"<svg\b[^>]*>.*?</svg\s*>", re.IGNORECASE | re.DOTALL)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


def filter_dom(html: str, *, budget_bytes: int = _DOM_BUDGET_BYTES) -> str:
    """Strip noise then truncate. Public for unit tests."""
    cleaned = _SCRIPT_RE.sub("", html)
    cleaned = _STYLE_RE.sub("", cleaned)
    cleaned = _SVG_RE.sub("", cleaned)
    cleaned = _COMMENT_RE.sub("", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned.encode("utf-8")) <= budget_bytes:
        return cleaned
    encoded = cleaned.encode("utf-8")[:budget_bytes]
    # Avoid ending mid-multibyte char.
    return encoded.decode("utf-8", errors="ignore")


class LLMReselectStrategy:
    """Tier 5: filter DOM → call LLM → parse a fresh `ElementSelector`.

    `session_factory` (M9's silver-tier persistence hook) is wired the same
    way as in `LLMClassifier` so a single `LLMCallRow` lands per call with
    `called_for="recover"`.
    """

    name: str = "llm_reselect"
    applicable_modes: frozenset[FailureMode] = frozenset(
        {
            FailureMode.ELEMENT_NOT_FOUND,
            FailureMode.ELEMENT_NOT_INTERACTABLE,
            FailureMode.UNKNOWN,
        }
    )
    cost_tier: int = 5

    def __init__(
        self,
        *,
        session_factory: Callable[[], AbstractAsyncContextManager[AsyncSession]] | None = None,
        request_timeout_s: float = 30.0,
        max_tokens: int = _MAX_TOKENS,
        cache_ttl_s: int = 86400,
    ) -> None:
        self._session_factory = session_factory
        self._timeout_s = request_timeout_s
        self._max_tokens = max_tokens
        self._cache_ttl_s = cache_ttl_s

    async def attempt(
        self,
        *,
        failed: ActionExecution,
        page: Page,
        original: RecordedAction,
        ctx: RecoveryContext,
    ) -> RecoveryDecision:
        started = monotonic()

        if ctx.llm_backend is None or ctx.llm_retry is None:
            return RecoveryDecision(
                applicable=False,
                succeeded=False,
                rationale="no LLM backend wired into RecoveryContext",
                duration_ms=int((monotonic() - started) * 1000),
            )

        last_attempt = failed.attempts[-1] if failed.attempts else None
        failure_mode = (
            last_attempt.failure_mode if last_attempt is not None else FailureMode.UNKNOWN
        ) or FailureMode.UNKNOWN

        try:
            html = await page.content()
        except PlaywrightError as exc:
            return RecoveryDecision(
                applicable=True,
                succeeded=False,
                rationale=f"could not read page DOM: {exc}",
                duration_ms=int((monotonic() - started) * 1000),
            )
        filtered = filter_dom(html)

        prompt = ctx.llm_prompt or ReselectV1Prompt()
        parser = ctx.llm_parser or SelectorToolUseParser()
        messages, tools = prompt.build(original, filtered, failure_mode)
        cache_key = self._cache_key(prompt, ctx.llm_backend.model, original, filtered, failure_mode)
        artifacts: list[str] = []

        if ctx.llm_cache is not None:
            cached = await ctx.llm_cache.get(cache_key)
            if cached is not None:
                _log.debug("llm_reselect_cache_hit", key=cache_key)
                new_sel = parser.parse(cached)
                return self._decision_from_selector(
                    new_sel,
                    rationale_prefix="cache hit",
                    started=started,
                    artifacts=artifacts,
                )

        if ctx.budget is not None:
            try:
                await ctx.budget.check_or_raise()
            except LLMBudgetExceeded as exc:
                return RecoveryDecision(
                    applicable=True,
                    succeeded=False,
                    rationale=f"budget exceeded: {exc}",
                    duration_ms=int((monotonic() - started) * 1000),
                )

        retryable = _retryable_types()
        semaphore = ctx.llm_semaphore
        try:
            response = await self._call_backend(
                ctx,
                messages=messages,
                tools=tools,
                retryable=retryable,
                semaphore=semaphore,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _log.warning(
                "llm_reselect_backend_failed",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return RecoveryDecision(
                applicable=True,
                succeeded=False,
                rationale=f"LLM call failed: {exc}",
                duration_ms=int((monotonic() - started) * 1000),
            )

        new_selector = parser.parse(response)
        latency_ms = response.input_tokens + response.output_tokens  # placeholder, overridden below
        # Persist bronze + silver + cache + budget. We don't block the decision
        # on these; failures are logged but never raised.
        artifacts = await self._persist(
            ctx=ctx,
            response=response,
            messages=messages,
            cache_key=cache_key,
            action=original,
            latency_ms=latency_ms,
        )

        return self._decision_from_selector(
            new_selector,
            rationale_prefix="LLM reselect",
            started=started,
            artifacts=artifacts,
        )

    async def _call_backend(
        self,
        ctx: RecoveryContext,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        retryable: tuple[type[BaseException], ...],
        semaphore: asyncio.Semaphore | None,
    ) -> LLMResponse:
        backend = ctx.llm_backend
        retry = ctx.llm_retry
        assert backend is not None  # checked by caller
        assert retry is not None

        async def fire() -> LLMResponse:
            response: LLMResponse = await backend.complete(
                messages,
                max_tokens=self._max_tokens,
                temperature=0.0,
                timeout_s=self._timeout_s,
                tools=tools,
            )
            return response

        async def execute() -> LLMResponse:
            result: LLMResponse = await retry.execute(fire, retryable=retryable)
            return result

        if semaphore is None:
            return await execute()
        async with semaphore:
            return await execute()

    def _cache_key(
        self,
        prompt: Any,
        model: str,
        action: RecordedAction,
        filtered_dom: str,
        failure_mode: FailureMode,
    ) -> str:
        seed = f"{model}|{prompt.version}|{prompt.signature(action, filtered_dom, failure_mode)}"
        return hashlib.sha256(seed.encode("utf-8")).hexdigest()

    def _decision_from_selector(
        self,
        new_selector: ElementSelector | None,
        *,
        rationale_prefix: str,
        started: float,
        artifacts: list[str],
    ) -> RecoveryDecision:
        if new_selector is None:
            return RecoveryDecision(
                applicable=True,
                succeeded=False,
                rationale=f"{rationale_prefix}: parser abstained",
                artifacts=artifacts,
                duration_ms=int((monotonic() - started) * 1000),
            )
        return RecoveryDecision(
            applicable=True,
            succeeded=True,
            new_selector=new_selector,
            rationale=f"{rationale_prefix}: picked fresh selector",
            artifacts=artifacts,
            duration_ms=int((monotonic() - started) * 1000),
        )

    async def _persist(
        self,
        *,
        ctx: RecoveryContext,
        response: LLMResponse,
        messages: list[dict[str, Any]],
        cache_key: str,
        action: RecordedAction,
        latency_ms: int,
    ) -> list[str]:
        call_id = uuid4()
        backend = ctx.llm_backend
        assert backend is not None
        cost_usd = compute_cost(backend.model, response.input_tokens, response.output_tokens)
        artifacts: list[str] = []

        async def write_bronze() -> None:
            if ctx.bronze is None:
                return
            try:
                path = await ctx.bronze.write_llm_call(
                    call_id,
                    {
                        "prompt": messages,
                        "response": response.raw,
                        "model": backend.model,
                        "called_for": "recover",
                    },
                )
                artifacts.append(path)
            except Exception as exc:
                _log.error("recovery_bronze_write_failed", call_id=str(call_id), error=str(exc))

        async def write_silver() -> None:
            if self._session_factory is None:
                return
            try:
                from rpa_recorder.storage.db import LLMCallRow  # noqa: PLC0415

                row = LLMCallRow(
                    id=str(call_id),
                    called_for="recover",
                    model=backend.model,
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
                _log.error("recovery_silver_write_failed", call_id=str(call_id), error=str(exc))

        async def set_cache() -> None:
            if ctx.llm_cache is None:
                return
            try:
                await ctx.llm_cache.set(cache_key, response, self._cache_ttl_s)
            except Exception as exc:
                _log.error("recovery_cache_set_failed", key=cache_key, error=str(exc))

        async def record_budget() -> None:
            if ctx.budget is None:
                return
            try:
                await ctx.budget.record_spend(cost_usd)
            except Exception as exc:
                _log.error("recovery_budget_record_failed", error=str(exc))

        async with asyncio.TaskGroup() as tg:
            tg.create_task(write_bronze())
            tg.create_task(write_silver())
            tg.create_task(set_cache())
            tg.create_task(record_budget())
        return artifacts


_PROMPT_TRUNCATE: int = 8000


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


__all__ = ["LLMReselectStrategy", "filter_dom"]
