"""`rpa show <id>` — pretty-print a recording with intents and confidence."""

from uuid import UUID

import typer

from rpa_recorder.cli.app import app
from rpa_recorder.cli.async_runner import run_async
from rpa_recorder.cli.console import console
from rpa_recorder.cli.dependencies import init_database, make_session_factory
from rpa_recorder.cli.errors import CLIError, handle_cli_errors
from rpa_recorder.cli.output import render_recording_detail
from rpa_recorder.storage.repositories import RecordingRepository


@app.command(name="show")
@handle_cli_errors
def show(
    recording_id: str = typer.Argument(..., help="UUID of the recording to display."),
    redact: bool = typer.Option(
        True,
        "--redact/--no-redact",
        help="Mask values on inputs marked is_sensitive.",
    ),
) -> None:
    """Render a saved recording, one row per action."""
    run_async(_show_async)(recording_id=recording_id, redact=redact)


async def _show_async(*, recording_id: str, redact: bool) -> None:
    try:
        rec_uuid = UUID(recording_id)
    except ValueError as exc:
        raise CLIError(f"invalid UUID: {recording_id!r}") from exc
    await init_database()
    session_factory = make_session_factory()
    async with session_factory() as db:
        recording = await RecordingRepository(db).get(rec_uuid)
    if recording is None:
        raise CLIError(f"Recording not found: {rec_uuid}")
    console.print(render_recording_detail(recording, redact=redact))
