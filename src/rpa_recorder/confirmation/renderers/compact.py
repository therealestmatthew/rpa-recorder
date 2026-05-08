"""Default M11 renderer: one row per action in a Rich table.

Renderers are pure formatting. They never read from the DB, never write
to bronze, and never mutate state — easy to unit-test by rendering to a
`Console(record=True)` and asserting on captured text.
"""

from typing import TYPE_CHECKING, Any

from rich.table import Table

if TYPE_CHECKING:
    from rich.console import RenderableType

    from rpa_recorder.confirmation.protocol import ReviewSummary
    from rpa_recorder.models import RecordedAction, SemanticIntent


_VISIBLE_TEXT_LIMIT = 40


def _selector_summary(action: RecordedAction) -> str:
    sel = action.selector
    if sel is None:
        return "—"
    if sel.test_id:
        return f"test_id={sel.test_id}"
    if sel.role and sel.accessible_name:
        return f"{sel.role}[{sel.accessible_name}]"
    if sel.role:
        return sel.role
    if sel.text_content:
        return f"text={sel.text_content[:30]}"
    return sel.css or sel.xpath or "—"


def _truncate(text: str | None, limit: int = _VISIBLE_TEXT_LIMIT) -> str:
    if text is None:
        return "—"
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


class CompactRenderer:
    """Single-row-per-action table with the essentials for rapid review."""

    name = "compact"

    def render_action(
        self,
        action: RecordedAction,
        *,
        context: dict[str, Any] | None = None,
    ) -> RenderableType:
        del context
        table = Table(title=f"Action #{action.sequence}", show_header=True)
        table.add_column("Field", style="accent")
        table.add_column("Value")
        intent = action.semantic_intent.value
        if action.user_label:
            intent = f"{intent} (user: {action.user_label})"
        table.add_row("intent", intent)
        table.add_row("confidence", f"{action.classification_confidence:.2f}")
        table.add_row("type", action.action_type.value)
        table.add_row("selector", _selector_summary(action))
        text = action.element_context.visible_text if action.element_context is not None else None
        table.add_row("visible_text", _truncate(text))
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
        table.add_column("selector")
        table.add_column("visible_text")
        for action in actions:
            text = (
                action.element_context.visible_text if action.element_context is not None else None
            )
            table.add_row(
                str(action.sequence),
                f"{action.classification_confidence:.2f}",
                _selector_summary(action),
                _truncate(text),
            )
        return table


__all__ = ["CompactRenderer"]
