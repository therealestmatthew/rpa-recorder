"""`rpa record <name> --url <url> [--headless]` — interactive capture.

Opens a `BrowserSession`, attaches a `Recorder` (with a `BronzeWriter` so raw
envelopes also land in `data/bronze/recordings/<id>/raw_events.jsonl`), and
waits for Ctrl+C to stop. On stop, the M7 heuristic engine classifies every
captured action and the recording is saved through `RecordingRepository`.
"""

import asyncio
from typing import TYPE_CHECKING

import typer

from rpa_recorder.browser.recorder import Recorder
from rpa_recorder.browser.session import BrowserSession
from rpa_recorder.classifier.heuristic import default_pipeline
from rpa_recorder.cli.app import app
from rpa_recorder.cli.async_runner import run_async
from rpa_recorder.cli.console import console
from rpa_recorder.cli.dependencies import (
    init_database,
    make_bronze_writer_factory,
    make_session_factory,
)
from rpa_recorder.cli.errors import handle_cli_errors
from rpa_recorder.storage.repositories import RecordingRepository

if TYPE_CHECKING:
    from rpa_recorder.models import Recording


@app.command(name="record")
@handle_cli_errors
def record(
    name: str = typer.Argument(..., help="Recording name."),
    url: str = typer.Option(..., "--url", help="Starting URL to open."),
    headless: bool = typer.Option(False, "--headless", help="Run the browser headless."),
) -> None:
    """Open a browser, record interactively, save on Ctrl+C."""
    run_async(_record_async)(name=name, url=url, headless=headless)


async def _record_async(*, name: str, url: str, headless: bool) -> None:
    await init_database()
    session_factory = make_session_factory()
    bronze_factory = make_bronze_writer_factory()

    async with session_factory() as db:
        bronze = bronze_factory(db)
        async with BrowserSession(headless=headless, bronze=bronze) as session:
            recorder = Recorder(
                session.page,
                name=name,
                starting_url=url,
                bronze=bronze,
            )
            await recorder.start()
            try:
                await session.page.goto(url)
                console.print("[dim]Recording. Press Ctrl+C to stop.[/dim]")
                await asyncio.Event().wait()
            finally:
                await recorder.stop()
                recording = _classify(recorder.get_recording())
                await RecordingRepository(db).save(recording)
                console.print(f"[success]Saved recording {recording.id}[/success]")


def _classify(recording: Recording) -> Recording:
    """Run the M7 heuristic over every recorded action and return a new `Recording`."""
    if not recording.actions:
        return recording
    engine = default_pipeline()
    classified = engine.process(recording.actions)
    new_actions = [
        action.model_copy(
            update={
                "semantic_intent": verdict.intent,
                "classification_confidence": verdict.confidence,
                "classification_reasoning": f"[{verdict.source}] {verdict.reasoning}",
            }
        )
        for action, verdict in classified
    ]
    return recording.model_copy(update={"actions": new_actions})
