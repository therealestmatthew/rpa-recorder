"""Retry policies for the LLM tier.

`ExponentialBackoffRetry` is the default. The Anthropic SDK has its own
internal retry layer; the `AnthropicBackend` constructs its client with
`max_retries=0` so this is the *only* retry layer (otherwise nested retries
multiply attempts and saturate rate limits unpredictably).

Retryable exceptions are passed in by the caller — the policy never decides
"what counts as retryable" on its own. `LLMBudgetExceeded` is excluded by
the caller list so it raises immediately with no extra delay.
"""

from __future__ import annotations

import asyncio
import secrets
from typing import TYPE_CHECKING, TypeVar

import structlog

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

T = TypeVar("T")

_log = structlog.get_logger(__name__)


class NoRetry:
    """Pass-through. Useful for tests that need deterministic single attempts."""

    async def execute(
        self,
        fn: Callable[[], Awaitable[T]],
        *,
        retryable: tuple[type[BaseException], ...],  # noqa: ARG002
    ) -> T:
        return await fn()


class ExponentialBackoffRetry:
    """1s, 2s, 4s, ... with optional ± jitter. Re-raises on final failure."""

    def __init__(
        self,
        *,
        max_attempts: int = 3,
        base_delay: float = 1.0,
        jitter: float = 0.5,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be ≥ 1")
        self._max_attempts = max_attempts
        self._base = base_delay
        self._jitter = jitter
        self._sleep = sleep if sleep is not None else asyncio.sleep

    async def execute(
        self,
        fn: Callable[[], Awaitable[T]],
        *,
        retryable: tuple[type[BaseException], ...],
    ) -> T:
        last_exc: BaseException | None = None
        for attempt in range(1, self._max_attempts + 1):
            try:
                return await fn()
            except retryable as exc:
                last_exc = exc
                if attempt >= self._max_attempts:
                    break
                delay = self._base * (2 ** (attempt - 1))
                if self._jitter:
                    # secrets.randbelow gives integer in [0, N); scale to ±jitter.
                    spread = self._jitter * 2.0
                    offset = (secrets.randbelow(1_000_001) / 1_000_000.0) * spread - self._jitter
                    delay = max(0.0, delay + offset)
                _log.info(
                    "llm_retry_attempt",
                    attempt=attempt,
                    next_delay_s=delay,
                    error=type(exc).__name__,
                )
                await self._sleep(delay)
        assert last_exc is not None  # mypy: retryable raised at least once
        raise last_exc


__all__ = ["ExponentialBackoffRetry", "NoRetry"]
