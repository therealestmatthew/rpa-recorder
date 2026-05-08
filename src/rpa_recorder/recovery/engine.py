"""`RecoveryEngine` — the per-failure orchestrator.

Filters strategies by the failed attempt's `FailureMode`, runs the survivors
in `cost_tier` ascending order, applies a per-strategy timeout, and after
each `succeeded=True` re-resolves the action's selector to defend against
hallucinated / accidental wins. Stops on first verified success. All
strategies are sequential — recovery is *not* parallelized.

Tier-5 (LLM) strategies use a wider timeout (`recovery_llm_timeout_s`)
because LLM round-trips legitimately exceed the regular 10 s cap.

Recursion is gated by `RecoveryContext.max_depth` (default 1): a recovered
action that itself fails does not trigger another recovery cycle.

When an `event_emitter` is supplied (M12 hook), the engine emits
`recovery_started`, `recovery_succeeded`, and `recovery_failed` events keyed
by the strategy `name` so the FastAPI control plane can stream progress.
"""

import asyncio
from contextlib import suppress
from typing import TYPE_CHECKING, Any

import structlog

from rpa_recorder.config import Config
from rpa_recorder.models import RecoveryAction

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

    from playwright.async_api import Page

    from rpa_recorder.models import (
        ActionExecution,
        ElementSelector,
        RecordedAction,
    )

    from .protocol import RecoveryContext, Strategy

_log = structlog.get_logger(__name__)

_LLM_COST_TIER: int = 5


EventEmitter = "Callable[[str, dict[str, Any]], Awaitable[None] | None]"


class RecoveryEngine:
    """Run applicable strategies in cost order; verify each `succeeded` win."""

    def __init__(
        self,
        strategies: Sequence[Strategy],
        *,
        config: Config | None = None,
        event_emitter: Callable[[str, dict[str, Any]], Awaitable[None] | None] | None = None,
    ) -> None:
        self._strategies: list[Strategy] = sorted(strategies, key=lambda s: s.cost_tier)
        self._config = config if config is not None else Config()
        self._emit = event_emitter

    async def attempt(
        self,
        *,
        failed: ActionExecution,
        page: Page,
        original: RecordedAction,
        ctx: RecoveryContext,
        depth: int = 0,
    ) -> RecoveryAction | None:
        """Return a `RecoveryAction` on first verified success, else None.

        A `None` return tells the executor "all strategies declined or
        failed" — the action stays `FAILED`. Recursion past `ctx.max_depth`
        also returns None immediately.
        """
        if depth >= ctx.max_depth:
            _log.debug("recovery_max_depth_reached", depth=depth, max=ctx.max_depth)
            return None

        last_attempt = failed.attempts[-1] if failed.attempts else None
        failure_mode = last_attempt.failure_mode if last_attempt is not None else None
        if failure_mode is None:
            _log.debug("recovery_no_failure_mode", action_id=str(original.id))
            return None

        applicable = [s for s in self._strategies if failure_mode in s.applicable_modes]
        skipped = [s.name for s in self._strategies if failure_mode not in s.applicable_modes]
        _log.debug(
            "recovery_strategy_filter",
            failure_mode=failure_mode.value,
            applicable=[s.name for s in applicable],
            skipped=skipped,
        )

        for strategy in applicable:
            await self._fire("recovery_started", {"strategy": strategy.name})
            timeout = self._timeout_for(strategy)
            try:
                decision = await asyncio.wait_for(
                    strategy.attempt(
                        failed=failed,
                        page=page,
                        original=original,
                        ctx=ctx,
                    ),
                    timeout=timeout,
                )
            except TimeoutError:
                _log.info(
                    "recovery_strategy_timeout",
                    strategy=strategy.name,
                    timeout_s=timeout,
                )
                await self._fire(
                    "recovery_failed",
                    {"strategy": strategy.name, "reason": "timeout"},
                )
                continue
            except asyncio.CancelledError:
                # Propagate so the worker can drain cleanly.
                raise
            except Exception as exc:
                _log.warning(
                    "recovery_strategy_error",
                    strategy=strategy.name,
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
                await self._fire(
                    "recovery_failed",
                    {"strategy": strategy.name, "reason": "error", "error": str(exc)},
                )
                continue

            if not decision.applicable:
                _log.debug(
                    "recovery_strategy_skipped",
                    strategy=strategy.name,
                    rationale=decision.rationale,
                )
                continue
            if not decision.succeeded:
                _log.info(
                    "recovery_strategy_failed",
                    strategy=strategy.name,
                    rationale=decision.rationale,
                )
                await self._fire(
                    "recovery_failed",
                    {"strategy": strategy.name, "rationale": decision.rationale},
                )
                continue

            verifier_selector = decision.new_selector or original.selector
            if verifier_selector is not None and not await self._verify(page, verifier_selector):
                _log.info(
                    "recovery_strategy_verifier_rejected",
                    strategy=strategy.name,
                    rationale=decision.rationale,
                )
                await self._fire(
                    "recovery_failed",
                    {"strategy": strategy.name, "reason": "verifier_rejected"},
                )
                continue

            _log.info(
                "recovery_strategy_succeeded",
                strategy=strategy.name,
                duration_ms=decision.duration_ms,
            )
            await self._fire(
                "recovery_succeeded",
                {"strategy": strategy.name, "duration_ms": decision.duration_ms},
            )
            return RecoveryAction(
                strategy=strategy.name,
                rationale=decision.rationale,
                succeeded=True,
                new_selector=decision.new_selector,
            )

        return None

    def _timeout_for(self, strategy: Strategy) -> float:
        if strategy.cost_tier >= _LLM_COST_TIER:
            return self._config.recovery_llm_timeout_s
        return self._config.recovery_strategy_timeout_s

    async def _verify(self, page: Page, selector: ElementSelector) -> bool:
        """Re-resolve the selector via the executor's resolver. Return True iff it now resolves uniquely."""
        # Local import avoids a recovery → browser package cycle at module load.
        from rpa_recorder.browser.executor import (  # noqa: PLC0415
            SelectorResolutionError,
            resolve_selector,
        )

        try:
            await resolve_selector(page, selector)
        except SelectorResolutionError:
            return False
        except Exception as exc:
            _log.debug("recovery_verifier_error", error=str(exc))
            return False
        return True

    async def _fire(self, event: str, payload: dict[str, Any]) -> None:
        if self._emit is None:
            return
        with suppress(Exception):
            result = self._emit(event, payload)
            if asyncio.iscoroutine(result):
                await result


__all__ = ["RecoveryEngine"]
