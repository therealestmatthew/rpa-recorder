"""`rpa list` — show every recording in the database, newest first."""

from rpa_recorder.cli.app import app
from rpa_recorder.cli.async_runner import run_async
from rpa_recorder.cli.console import console
from rpa_recorder.cli.dependencies import init_database, make_session_factory
from rpa_recorder.cli.errors import handle_cli_errors
from rpa_recorder.cli.output import render_recording_summary
from rpa_recorder.storage.repositories import RecordingRepository


@app.command(name="list")
@handle_cli_errors
def list_recordings() -> None:
    """List every saved recording (newest first)."""
    run_async(_list_async)()


async def _list_async() -> None:
    await init_database()
    session_factory = make_session_factory()
    async with session_factory() as db:
        summaries = await RecordingRepository(db).list()
    console.print(render_recording_summary(summaries))
