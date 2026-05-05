"""`rpa replay <id> [--param k=v]... [--headless]` — replay a saved recording."""

from typing import TYPE_CHECKING
from uuid import UUID

import typer

from rpa_recorder.browser.executor import Executor
from rpa_recorder.browser.session import BrowserSession
from rpa_recorder.cli.app import app
from rpa_recorder.cli.async_runner import run_async
from rpa_recorder.cli.console import console
from rpa_recorder.cli.dependencies import (
    init_database,
    make_bronze_writer_factory,
    make_session_factory,
)
from rpa_recorder.cli.errors import CLIError, handle_cli_errors
from rpa_recorder.cli.output import render_run_result
from rpa_recorder.cli.params import collect_params
from rpa_recorder.storage.repositories import RecordingRepository, RunResultRepository

if TYPE_CHECKING:
    from rpa_recorder.models import RunResult


@app.command(name="replay")
@handle_cli_errors
def replay(
    recording_id: str = typer.Argument(..., help="UUID of the recording to replay."),
    param: list[str] = typer.Option(
        [],
        "--param",
        help="Parameter substitution as key=value (repeatable).",
    ),
    headless: bool = typer.Option(False, "--headless", help="Run the browser headless."),
) -> None:
    """Replay a saved recording and render the result."""
    parameters = collect_params(param)
    run_async(_replay_async)(
        recording_id=recording_id,
        parameters=parameters,
        headless=headless,
    )


async def _replay_async(
    *,
    recording_id: str,
    parameters: dict[str, str],
    headless: bool,
) -> None:
    try:
        rec_uuid = UUID(recording_id)
    except ValueError as exc:
        raise CLIError(f"invalid UUID: {recording_id!r}") from exc

    await init_database()
    session_factory = make_session_factory()
    bronze_factory = make_bronze_writer_factory()

    async with session_factory() as db:
        recording = await RecordingRepository(db).get(rec_uuid)
        if recording is None:
            raise CLIError(f"Recording not found: {rec_uuid}")
        bronze = bronze_factory(db)
        async with BrowserSession(headless=headless) as session:
            executor = Executor(
                session.page,
                recording,
                bronze=bronze,
                parameter_values=parameters,
            )
            run_result: RunResult = await executor.run()
        await RunResultRepository(db).save(run_result)
    console.print(render_run_result(run_result))
