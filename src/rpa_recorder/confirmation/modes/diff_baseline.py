"""M11 review mode: show only actions whose intent has changed since baseline.

Useful after re-classifying with a new prompt or heuristic — the user only
reviews what actually moved. Without an audit log to compare against, falls
back to running every candidate through the inner mode.
"""

from typing import TYPE_CHECKING

from rpa_recorder.confirmation.modes.per_action import PerActionMode

if TYPE_CHECKING:
    from datetime import datetime

    from rpa_recorder.confirmation.protocol import (
        ActionReviewResult,
        OnDecision,
        Renderer,
    )
    from rpa_recorder.models import RecordedAction


class DiffBaselineMode:
    """Filter candidates against a baseline-snapshot map of action_id → intent."""

    name = "diff_baseline"

    def __init__(
        self,
        baseline_at: datetime,
        baseline_intents: dict[str, str] | None = None,
        fallback: PerActionMode | None = None,
    ) -> None:
        self._baseline_at = baseline_at
        self._baseline = baseline_intents or {}
        self._fallback = fallback or PerActionMode()

    async def review(
        self,
        candidates: list[RecordedAction],
        *,
        renderer: Renderer,
        on_decision: OnDecision,
    ) -> list[ActionReviewResult]:
        if not self._baseline:
            return await self._fallback.review(
                candidates, renderer=renderer, on_decision=on_decision
            )
        changed = [
            a for a in candidates if self._baseline.get(str(a.id)) != a.semantic_intent.value
        ]
        return await self._fallback.review(changed, renderer=renderer, on_decision=on_decision)


__all__ = ["DiffBaselineMode"]
