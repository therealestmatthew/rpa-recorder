"""Tier-2 recovery: close a blocking dialog via its standard close affordance.

State-mutating and irreversible — once the modal is closed it can't be
reopened. If `dismiss_modal` succeeds but the underlying target is still
blocked, the engine still moves on to the next strategy, but the page state
has changed permanently. Document this expectation in tests / runbooks.
"""

from time import monotonic
from typing import TYPE_CHECKING

from playwright.async_api import Error as PlaywrightError

from rpa_recorder.models import FailureMode
from rpa_recorder.recovery.protocol import RecoveryContext, RecoveryDecision

if TYPE_CHECKING:
    from playwright.async_api import Page

    from rpa_recorder.models import ActionExecution, RecordedAction


_CLOSE_SELECTOR = (
    "[role=dialog] [aria-label*=close i],"
    " [role=dialog] button:has-text('Close'),"
    " [role=dialog] [aria-label*=dismiss i]"
)
_CLICK_TIMEOUT_MS: int = 2000


class DismissModalStrategy:
    """Tier 2: click the first dialog close affordance found."""

    name: str = "dismiss_modal"
    applicable_modes: frozenset[FailureMode] = frozenset(
        {FailureMode.ELEMENT_NOT_INTERACTABLE, FailureMode.UNEXPECTED_MODAL}
    )
    cost_tier: int = 2

    async def attempt(
        self,
        *,
        failed: ActionExecution,  # noqa: ARG002
        page: Page,
        original: RecordedAction,  # noqa: ARG002
        ctx: RecoveryContext,  # noqa: ARG002
    ) -> RecoveryDecision:
        started = monotonic()
        close_locator = page.locator(_CLOSE_SELECTOR)
        try:
            count = await close_locator.count()
        except PlaywrightError as exc:
            return RecoveryDecision(
                applicable=True,
                succeeded=False,
                rationale=f"could not probe dialog: {exc}",
                duration_ms=int((monotonic() - started) * 1000),
            )
        if count == 0:
            return RecoveryDecision(
                applicable=True,
                succeeded=False,
                rationale="no dialog close affordance found",
                duration_ms=int((monotonic() - started) * 1000),
            )

        try:
            await close_locator.first.click(timeout=_CLICK_TIMEOUT_MS)
        except (TimeoutError, PlaywrightError) as exc:
            return RecoveryDecision(
                applicable=True,
                succeeded=False,
                rationale=f"close click failed: {exc}",
                duration_ms=int((monotonic() - started) * 1000),
            )
        return RecoveryDecision(
            applicable=True,
            succeeded=True,
            rationale="dismissed modal via close affordance",
            duration_ms=int((monotonic() - started) * 1000),
        )


__all__ = ["DismissModalStrategy"]
