"""Cheapest tier-0 recovery: pause for slow SPAs to settle.

No mutation, no new selector. The post-recovery verifier in `RecoveryEngine`
defends against false positives — if the element still isn't there after the
wait, the verifier rejects and the engine moves on to the next strategy.
"""

from time import monotonic
from typing import TYPE_CHECKING

from playwright.async_api import Error as PlaywrightError

from rpa_recorder.models import FailureMode
from rpa_recorder.recovery.protocol import RecoveryContext, RecoveryDecision

if TYPE_CHECKING:
    from playwright.async_api import Page

    from rpa_recorder.models import ActionExecution, RecordedAction


_DEFAULT_WAIT_MS: int = 500


class WaitAndRetryStrategy:
    """Tier 0: 500 ms quiet pause. Lets DOM mutations and animations finish."""

    name: str = "wait_and_retry"
    applicable_modes: frozenset[FailureMode] = frozenset(
        {FailureMode.TIMEOUT, FailureMode.ELEMENT_NOT_INTERACTABLE}
    )
    cost_tier: int = 0

    def __init__(self, wait_ms: int = _DEFAULT_WAIT_MS) -> None:
        self._wait_ms = wait_ms

    async def attempt(
        self,
        *,
        failed: ActionExecution,  # noqa: ARG002
        page: Page,
        original: RecordedAction,  # noqa: ARG002
        ctx: RecoveryContext,  # noqa: ARG002
    ) -> RecoveryDecision:
        started = monotonic()
        try:
            await page.wait_for_timeout(self._wait_ms)
        except PlaywrightError as exc:
            return RecoveryDecision(
                applicable=True,
                succeeded=False,
                rationale=f"wait failed: {exc}",
                duration_ms=int((monotonic() - started) * 1000),
            )
        return RecoveryDecision(
            applicable=True,
            succeeded=True,
            rationale=f"waited {self._wait_ms}ms for DOM to settle",
            duration_ms=int((monotonic() - started) * 1000),
        )


__all__ = ["WaitAndRetryStrategy"]
