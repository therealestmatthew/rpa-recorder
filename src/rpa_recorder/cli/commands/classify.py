"""`rpa classify <id>` — re-run the M7 heuristic over a saved recording.

The command loads the recording, reruns `default_pipeline()` against it, and
overwrites the `semantic_intent`, `classification_confidence`, and
`classification_reasoning` columns. Reasoning is prefixed with `[<source>]`
so M11.5 can decide later whether `source` deserves its own column.
M9 extends this command to consult the LLM tier when the heuristic's
confidence falls below `Config.classifier_confidence_threshold`.
"""

from uuid import UUID

import typer

from rpa_recorder.classifier.heuristic import default_pipeline
from rpa_recorder.cli.app import app
from rpa_recorder.cli.async_runner import run_async
from rpa_recorder.cli.console import console
from rpa_recorder.cli.dependencies import init_database, make_session_factory
from rpa_recorder.cli.errors import CLIError, handle_cli_errors
from rpa_recorder.storage.repositories import RecordingRepository


@app.command(name="classify")
@handle_cli_errors
def classify(
    recording_id: str = typer.Argument(..., help="UUID of the recording to classify."),
) -> None:
    """Re-run the heuristic classifier over a saved recording."""
    run_async(_classify_async)(recording_id=recording_id)


async def _classify_async(*, recording_id: str) -> None:
    try:
        rec_uuid = UUID(recording_id)
    except ValueError as exc:
        raise CLIError(f"invalid UUID: {recording_id!r}") from exc

    await init_database()
    session_factory = make_session_factory()
    async with session_factory() as db:
        repo = RecordingRepository(db)
        recording = await repo.get(rec_uuid)
        if recording is None:
            raise CLIError(f"Recording not found: {rec_uuid}")
        engine = default_pipeline()
        classified = engine.process(recording.actions)
        new_actions = [
            action.model_copy(
                update={
                    "semantic_intent": verdict.intent,
                    "classification_confidence": verdict.confidence,
                    "classification_reasoning": (f"[{verdict.source}] {verdict.reasoning}"),
                }
            )
            for action, verdict in classified
        ]
        # Replace by deleting + re-saving with classified actions. Simpler than
        # crafting a partial update and within the same transaction.
        await repo.delete(rec_uuid)
        await repo.save(recording.model_copy(update={"actions": new_actions}))
    console.print(
        f"[success]Re-classified {len(classified)} actions for recording {rec_uuid}[/success]"
    )
