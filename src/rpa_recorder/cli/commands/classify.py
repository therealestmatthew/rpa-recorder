"""`rpa classify <id>` — re-classify a saved recording with the hybrid classifier.

Loads the recording, runs `default_classifier()` (M9 hybrid: M7 heuristic
first, LLM tier on uncertain actions), and overwrites `semantic_intent`,
`classification_confidence`, and `classification_reasoning`. Reasoning is
prefixed with `[<source>]` so M11.5 can break out heuristic-vs-LLM
accuracy from the column without a separate `source` field.

Bronze writes for the LLM tier are skipped from the CLI path (no
session-binding plumbing here). M11.5's worker wires up the full
bronze + silver persistence per call.
"""

from uuid import UUID

import typer

from rpa_recorder.classifier import default_classifier
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
    """Re-run the hybrid classifier (heuristic + LLM) over a saved recording."""
    run_async(_classify_async)(recording_id=recording_id)


async def _classify_async(*, recording_id: str) -> None:
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

    classifier = default_classifier(session_factory=session_factory)
    verdicts = await classifier.classify_batch(recording.actions)

    new_actions = [
        action.model_copy(
            update={
                "semantic_intent": verdict.intent,
                "classification_confidence": verdict.confidence,
                "classification_reasoning": f"[{verdict.source}] {verdict.reasoning}",
            }
        )
        for action, verdict in zip(recording.actions, verdicts, strict=True)
    ]

    async with session_factory() as db:
        repo = RecordingRepository(db)
        await repo.delete(rec_uuid)
        await repo.save(recording.model_copy(update={"actions": new_actions}))

    console.print(
        f"[success]Re-classified {len(new_actions)} actions for recording {rec_uuid}[/success]"
    )
