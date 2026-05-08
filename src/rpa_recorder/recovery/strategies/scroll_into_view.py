"""Tier-1 recovery: bring an off-screen target into the viewport.

Pure-page operation: never mutates DOM, only scrolls. If the locator can't
even be resolved (cardinality != 1), the strategy declines (`applicable=True,
succeeded=False`) so the engine can move on to a strategy that handles the
"target gone" case.
"""

from time import monotonic
from typing import TYPE_CHECKING

from playwright.async_api import Error as PlaywrightError

from rpa_recorder.models import FailureMode
from rpa_recorder.recovery.protocol import RecoveryContext, RecoveryDecision

if TYPE_CHECKING:
    from playwright.async_api import Page

    from rpa_recorder.models import ActionExecution, RecordedAction


class ScrollIntoViewStrategy:
    """Tier 1: scroll the original selector's target into view if needed."""

    name: str = "scroll_into_view"
    applicable_modes: frozenset[FailureMode] = frozenset({FailureMode.ELEMENT_NOT_INTERACTABLE})
    cost_tier: int = 1

    async def attempt(
        self,
        *,
        failed: ActionExecution,  # noqa: ARG002
        page: Page,
        original: RecordedAction,
        ctx: RecoveryContext,  # noqa: ARG002
    ) -> RecoveryDecision:
        started = monotonic()
        sel = original.selector
        if sel is None:
            return RecoveryDecision(
                applicable=False,
                succeeded=False,
                rationale="no selector to scroll into view",
                duration_ms=int((monotonic() - started) * 1000),
            )

        # Local import keeps recovery package decoupled at module load.
        from rpa_recorder.browser.executor import (  # noqa: PLC0415
            SelectorResolutionError,
            resolve_selector,
        )

        try:
            locator, _ = await resolve_selector(page, sel)
        except SelectorResolutionError:
            return RecoveryDecision(
                applicable=True,
                succeeded=False,
                rationale="selector did not resolve uniquely",
                duration_ms=int((monotonic() - started) * 1000),
            )

        try:
            visible = await locator.is_visible()
        except PlaywrightError as exc:
            return RecoveryDecision(
                applicable=True,
                succeeded=False,
                rationale=f"visibility probe failed: {exc}",
                duration_ms=int((monotonic() - started) * 1000),
            )
        if visible:
            return RecoveryDecision(
                applicable=True,
                succeeded=True,
                rationale="element already visible",
                duration_ms=int((monotonic() - started) * 1000),
            )

        try:
            await locator.scroll_into_view_if_needed()
        except PlaywrightError as exc:
            return RecoveryDecision(
                applicable=True,
                succeeded=False,
                rationale=f"scroll failed: {exc}",
                duration_ms=int((monotonic() - started) * 1000),
            )
        return RecoveryDecision(
            applicable=True,
            succeeded=True,
            rationale="scrolled element into view",
            duration_ms=int((monotonic() - started) * 1000),
        )


__all__ = ["ScrollIntoViewStrategy"]
