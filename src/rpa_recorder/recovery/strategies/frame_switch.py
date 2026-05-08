"""Tier-2 recovery: hunt the original selector down inside an iframe.

Walks `page.frames`; for each non-main frame, builds a locator from the
original `ElementSelector` (without `frame_url`) and checks for cardinality
exactly 1. On a match returns a new `ElementSelector` with `frame_url` set so
the executor's locator path resolves the action inside that frame on retry.
"""

from time import monotonic
from typing import TYPE_CHECKING

from playwright.async_api import Error as PlaywrightError

from rpa_recorder.models import ElementSelector, FailureMode
from rpa_recorder.recovery.protocol import RecoveryContext, RecoveryDecision

if TYPE_CHECKING:
    from playwright.async_api import Frame, Locator, Page

    from rpa_recorder.models import ActionExecution, RecordedAction


def _candidate_locators(frame: Frame, sel: ElementSelector) -> list[Locator]:
    """Build the same multi-strategy locator list as the executor, scoped to a frame."""
    candidates: list[Locator] = []
    if sel.test_id:
        candidates.append(frame.get_by_test_id(sel.test_id))
    if sel.role and sel.accessible_name:
        candidates.append(frame.get_by_role(sel.role, name=sel.accessible_name))  # type: ignore[arg-type]
    if sel.text_content:
        candidates.append(frame.get_by_text(sel.text_content, exact=True))
    if sel.css:
        candidates.append(frame.locator(sel.css))
    if sel.xpath:
        candidates.append(frame.locator(f"xpath={sel.xpath}"))
    return candidates


class FrameSwitchStrategy:
    """Tier 2: try resolving the original selector in each iframe.

    Returns a new selector with `frame_url` populated; the executor uses it
    to scope replay to that frame on retry.
    """

    name: str = "frame_switch"
    applicable_modes: frozenset[FailureMode] = frozenset({FailureMode.ELEMENT_NOT_FOUND})
    cost_tier: int = 2

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
                rationale="no selector to relocate",
                duration_ms=int((monotonic() - started) * 1000),
            )

        # Strip frame_url so we don't recursively re-use a stale frame hint.
        bare = sel.model_copy(update={"frame_url": None})
        frames = [f for f in page.frames if f is not page.main_frame]
        if not frames:
            return RecoveryDecision(
                applicable=True,
                succeeded=False,
                rationale="page has no iframes",
                duration_ms=int((monotonic() - started) * 1000),
            )

        for frame in frames:
            for candidate in _candidate_locators(frame, bare):
                try:
                    count = await candidate.count()
                except PlaywrightError:
                    continue
                if count == 1:
                    new_sel = bare.model_copy(update={"frame_url": frame.url})
                    return RecoveryDecision(
                        applicable=True,
                        succeeded=True,
                        new_selector=new_sel,
                        rationale=f"located target inside iframe {frame.url}",
                        duration_ms=int((monotonic() - started) * 1000),
                    )

        return RecoveryDecision(
            applicable=True,
            succeeded=False,
            rationale="no iframe contained the target",
            duration_ms=int((monotonic() - started) * 1000),
        )


__all__ = ["FrameSwitchStrategy"]
