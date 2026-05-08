"""M11 side-by-side renderer: heuristic vs LLM verdict columns.

Parses `[heuristic:<rule>]` and `[llm]` markers in `classification_reasoning`
(the source-attribution format M9 emits) so the user can compare the two
classifier verdicts when only one fired in the confirmation flow.
"""

import re
from typing import TYPE_CHECKING, Any

from rich.table import Table

if TYPE_CHECKING:
    from rich.console import RenderableType

    from rpa_recorder.confirmation.protocol import ReviewSummary
    from rpa_recorder.models import RecordedAction, SemanticIntent


_HEURISTIC = re.compile(r"\[heuristic:([^\]]+)\]\s*([^;\[]+)")
_LLM = re.compile(r"\[llm\]\s*([^;\[]+)")


def _parse_reasoning(reasoning: str | None) -> tuple[str, str]:
    """Return `(heuristic_part, llm_part)` parsed out of a tagged string."""
    if not reasoning:
        return ("—", "—")
    h_match = _HEURISTIC.search(reasoning)
    l_match = _LLM.search(reasoning)
    heuristic = f"{h_match.group(1).strip()}: {h_match.group(2).strip()}" if h_match else "—"
    llm = l_match.group(1).strip() if l_match else "—"
    return (heuristic, llm)


class SideBySideRenderer:
    """Two-column verdict view; useful for re-classification audits."""

    name = "side_by_side"

    def render_action(
        self,
        action: RecordedAction,
        *,
        context: dict[str, Any] | None = None,
    ) -> RenderableType:
        del context
        heuristic, llm = _parse_reasoning(action.classification_reasoning)
        table = Table(title=f"Action #{action.sequence} (side-by-side)", show_header=True)
        table.add_column("Source", style="accent")
        table.add_column("Verdict")
        table.add_row("intent", action.semantic_intent.value)
        table.add_row("confidence", f"{action.classification_confidence:.2f}")
        table.add_row("heuristic", heuristic)
        table.add_row("llm", llm)
        return table

    def render_summary(self, summary: ReviewSummary) -> RenderableType:
        table = Table(title="Review summary", show_header=True)
        table.add_column("Metric", style="accent")
        table.add_column("Value", justify="right")
        table.add_row("recording_id", str(summary.recording_id))
        table.add_row("candidates", str(summary.total_candidates))
        table.add_row("accepted", str(summary.accepted))
        table.add_row("relabeled", str(summary.relabeled))
        table.add_row("skipped", str(summary.skipped))
        table.add_row("duration_s", f"{summary.duration_s:.2f}")
        return table

    def render_intent_batch(
        self,
        intent: SemanticIntent,
        actions: list[RecordedAction],
    ) -> RenderableType:
        table = Table(title=f"Intent group: {intent.value} ({len(actions)})")
        table.add_column("seq", justify="right")
        table.add_column("conf", justify="right")
        table.add_column("heuristic")
        table.add_column("llm")
        for action in actions:
            heuristic, llm = _parse_reasoning(action.classification_reasoning)
            table.add_row(
                str(action.sequence),
                f"{action.classification_confidence:.2f}",
                heuristic,
                llm,
            )
        return table


__all__ = ["SideBySideRenderer"]
