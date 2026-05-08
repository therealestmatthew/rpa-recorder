"""M11 detailed renderer: full element_context + redacted payload + reasoning.

Used by `rpa confirm --renderer detailed` when the compact view doesn't
give enough context to relabel confidently.
"""

from typing import TYPE_CHECKING, Any

from rich.table import Table

if TYPE_CHECKING:
    from rich.console import RenderableType

    from rpa_recorder.confirmation.protocol import ReviewSummary
    from rpa_recorder.models import RecordedAction, SemanticIntent


class DetailedRenderer:
    """Renders the full element context + redacted payload + reasoning."""

    name = "detailed"

    def render_action(
        self,
        action: RecordedAction,
        *,
        context: dict[str, Any] | None = None,
    ) -> RenderableType:
        del context
        table = Table(title=f"Action #{action.sequence} (detailed)", show_header=True)
        table.add_column("Field", style="accent")
        table.add_column("Value")
        intent = action.semantic_intent.value
        if action.user_label:
            intent = f"{intent} (user: {action.user_label})"
        table.add_row("intent", intent)
        table.add_row("confidence", f"{action.classification_confidence:.2f}")
        table.add_row("type", action.action_type.value)
        table.add_row("url", action.url)

        ctx = action.element_context
        if ctx is not None:
            table.add_row("tag", ctx.tag)
            if ctx.visible_text:
                table.add_row("visible_text", ctx.visible_text)
            if ctx.attributes:
                attrs = ", ".join(f"{k}={v}" for k, v in ctx.attributes.items())
                table.add_row("attributes", attrs)
            if ctx.parent_form_id:
                table.add_row("parent_form_id", ctx.parent_form_id)
            if ctx.nearby_labels:
                table.add_row("nearby_labels", " | ".join(ctx.nearby_labels))

        # Redact sensitive payload fields per the action's own serializer rules.
        payload_dump = action.model_dump(context={"redact_secrets": True})["payload"]
        table.add_row("payload", str(payload_dump))

        if action.classification_reasoning:
            table.add_row("reasoning", action.classification_reasoning)
        return table

    def render_summary(self, summary: ReviewSummary) -> RenderableType:
        table = Table(title="Review summary (detailed)", show_header=True)
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
        table.add_column("type")
        table.add_column("conf", justify="right")
        table.add_column("reasoning")
        for action in actions:
            table.add_row(
                str(action.sequence),
                action.action_type.value,
                f"{action.classification_confidence:.2f}",
                action.classification_reasoning or "—",
            )
        return table


__all__ = ["DetailedRenderer"]
