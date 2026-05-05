"""Run-result renderers (replay summary + live progress lines)."""

from typing import TYPE_CHECKING, Any

from rich.table import Table
from rich.text import Text

from rpa_recorder.models import ExecutionStatus

if TYPE_CHECKING:
    from rich.console import RenderableType

    from rpa_recorder.models import RunResult


_STATUS_STYLE: dict[ExecutionStatus, str] = {
    ExecutionStatus.SUCCESS: "success",
    ExecutionStatus.FAILED: "error",
    ExecutionStatus.RECOVERED: "warning",
    ExecutionStatus.SKIPPED: "dim",
    ExecutionStatus.PENDING: "dim",
    ExecutionStatus.RUNNING: "accent",
    ExecutionStatus.AWAITING_CONFIRMATION: "warning",
}


def render_run_result(rr: RunResult) -> RenderableType:
    """Render `rpa replay` output: top-line status + per-action breakdown."""
    duration_ms: int | None = None
    if rr.ended_at is not None:
        duration_ms = int((rr.ended_at - rr.started_at).total_seconds() * 1000)

    table = Table(title=f"Run {rr.id}")
    table.add_column("Action", style="dim")
    table.add_column("Status")
    table.add_column("Attempts", justify="right")
    table.add_column("Duration ms", justify="right")
    table.add_column("Recovery")

    for ex in rr.executions:
        recovery = ex.recovery.strategy if ex.recovery is not None else ""
        table.add_row(
            str(ex.action_id),
            _status_text(ex.status),
            str(len(ex.attempts)),
            "" if ex.duration_ms is None else str(ex.duration_ms),
            recovery,
        )

    caption_parts = [f"status={rr.status.value}"]
    if duration_ms is not None:
        caption_parts.append(f"duration_ms={duration_ms}")
    table.caption = " · ".join(caption_parts)
    return table


def render_run_progress(event: dict[str, Any]) -> RenderableType:
    """Single-line renderable for one live progress event.

    Used by M12's `--follow` to print streaming WebSocket events. Expected
    keys: `action_id`, `status` (an `ExecutionStatus` value), and an optional
    `message`. Unknown statuses render the raw status string.
    """
    action_id = event.get("action_id", "?")
    status_raw = event.get("status", "?")
    message = event.get("message", "")
    try:
        status = ExecutionStatus(status_raw)
        status_renderable = _status_text(status)
    except ValueError:
        status_renderable = Text(str(status_raw))
    return Text.assemble(
        Text(f"{action_id} ", style="dim"),
        status_renderable,
        Text(f" {message}" if message else "", style="dim"),
    )


def _status_text(status: ExecutionStatus) -> Text:
    style = _STATUS_STYLE.get(status, "dim")
    return Text(status.value, style=style)


__all__ = ["render_run_progress", "render_run_result"]
