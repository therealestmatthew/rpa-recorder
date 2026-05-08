"""M11 review mode: full table + threshold-based bulk accept, manual remainder.

Avoids `rich.live.Live` so output is deterministic in `Console(record=True)`
test contexts. Uses `print` + `Prompt.ask` only.
"""

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from rich.prompt import Prompt
from rich.table import Table

from rpa_recorder.cli.console import console
from rpa_recorder.confirmation.modes.per_action import PerActionMode
from rpa_recorder.confirmation.protocol import (
    ActionReviewResult,
    Decision,
    OnDecision,
    Renderer,
)

if TYPE_CHECKING:
    from rpa_recorder.models import RecordedAction


def _overview_table(actions: list[RecordedAction]) -> Table:
    table = Table(title="Candidate overview", show_header=True)
    table.add_column("seq", justify="right")
    table.add_column("intent")
    table.add_column("conf", justify="right")
    table.add_column("type")
    for action in actions:
        table.add_row(
            str(action.sequence),
            action.semantic_intent.value,
            f"{action.classification_confidence:.2f}",
            action.action_type.value,
        )
    return table


class OverviewMode:
    """Show every candidate, then auto-accept above a chosen confidence cutoff."""

    name = "overview"

    def __init__(self, fallback: PerActionMode | None = None) -> None:
        self._fallback = fallback or PerActionMode()

    async def review(
        self,
        candidates: list[RecordedAction],
        *,
        renderer: Renderer,
        on_decision: OnDecision,
    ) -> list[ActionReviewResult]:
        console.print(_overview_table(candidates))
        cutoff_str = Prompt.ask(
            "auto-accept threshold (confidence >=)",
            default="1.0",
        )
        try:
            cutoff = float(cutoff_str)
        except ValueError:
            cutoff = 1.0

        auto: list[RecordedAction] = []
        manual: list[RecordedAction] = []
        for action in candidates:
            target = auto if action.classification_confidence >= cutoff else manual
            target.append(action)

        results: list[ActionReviewResult] = []
        for action in auto:
            result = ActionReviewResult(
                action_id=action.id,
                decision=Decision.ACCEPT,
                reviewed_at=datetime.now(UTC),
            )
            await on_decision(result)
            results.append(result)
        if auto:
            console.print(
                f"[success]auto-accepted {len(auto)}; reviewing {len(manual)} manually.[/success]"
            )
        results.extend(
            await self._fallback.review(manual, renderer=renderer, on_decision=on_decision)
        )
        return results


__all__ = ["OverviewMode"]
