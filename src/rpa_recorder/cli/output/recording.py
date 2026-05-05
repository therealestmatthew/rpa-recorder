"""Recording-shaped output renderers (table summaries + per-action detail)."""

from typing import TYPE_CHECKING

from rich.table import Table
from rich.text import Text

from rpa_recorder.models import REDACTED_VALUE, InputPayload, SemanticIntent

if TYPE_CHECKING:
    from collections.abc import Iterable

    from rich.console import RenderableType

    from rpa_recorder.models import Recording
    from rpa_recorder.storage.repositories import RecordingSummary


def render_recording_summary(recordings: Iterable[RecordingSummary]) -> RenderableType:
    """Render the `rpa list` table — one row per recording."""
    table = Table(title="Recordings")
    table.add_column("ID", style="dim")
    table.add_column("Name", style="accent")
    table.add_column("Created", style="dim")
    table.add_column("Actions", justify="right")
    for rec in recordings:
        table.add_row(
            str(rec.id),
            rec.name,
            rec.created_at.isoformat(),
            str(rec.action_count),
        )
    return table


def render_recording_detail(rec: Recording, *, redact: bool = True) -> RenderableType:
    """Per-action breakdown for `rpa show`. Sensitive payload values are masked.

    `redact=True` calls `model_dump(context={"redact_secrets": True})` on each
    `InputPayload`, so any field with `is_sensitive=True` reads `***REDACTED***`
    in the rendered output.
    """
    table = Table(title=f"{rec.name} ({rec.id})")
    table.add_column("#", justify="right", style="dim")
    table.add_column("Type", style="accent")
    table.add_column("Intent", style="highlight")
    table.add_column("Conf.", justify="right")
    table.add_column("Detail")
    for action in rec.actions:
        conf = f"{action.classification_confidence:.2f}"
        detail = _render_payload(action, redact=redact)
        table.add_row(
            str(action.sequence),
            action.action_type.value,
            _intent_text(action.semantic_intent),
            conf,
            detail,
        )
    return table


def _intent_text(intent: SemanticIntent) -> Text:
    style = "dim" if intent == SemanticIntent.UNKNOWN else "highlight"
    return Text(intent.value, style=style)


def _render_payload(action: object, *, redact: bool) -> str:
    payload = getattr(action, "payload", None)
    if isinstance(payload, InputPayload):
        if redact and payload.is_sensitive:
            return f"value={REDACTED_VALUE}"
        return f"value={payload.value!r}"
    if payload is None:
        return ""
    # ClickPayload, NavigatePayload, SelectPayload — let pydantic dump it.
    if hasattr(payload, "model_dump"):
        return ", ".join(f"{k}={v!r}" for k, v in payload.model_dump().items())
    return str(payload)


__all__ = ["render_recording_detail", "render_recording_summary"]
