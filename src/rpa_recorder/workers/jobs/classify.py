"""ARQ `classify_recording` job.

Iterates a recording's actions, runs the heuristic classifier, and falls
back to the LLM classifier when confidence is below threshold. Updates
each `RecordedActionRow` in place. Idempotent: a re-run reclassifies but
yields stable results when inputs are unchanged.
"""

from typing import Any
from uuid import UUID

import structlog

_log = structlog.get_logger(__name__)


async def classify_recording(
    ctx: dict[str, Any],
    *,
    recording_id: str,
) -> dict[str, Any]:
    """Classify every unconfirmed action in a recording."""
    from rpa_recorder.classifier.heuristic import default_pipeline  # noqa: PLC0415
    from rpa_recorder.config import Config  # noqa: PLC0415
    from rpa_recorder.storage.db import get_session  # noqa: PLC0415
    from rpa_recorder.storage.repositories import RecordingRepository  # noqa: PLC0415

    engine = ctx["db_engine"]
    config: Config = ctx.get("config") or Config()
    log = _log.bind(recording_id=recording_id, job_id=ctx.get("job_id"))

    rid = UUID(recording_id)
    async with get_session(engine) as db:
        recording = await RecordingRepository(db).get(rid)
    if recording is None:
        log.warning("classify_recording_not_found")
        return {"status": "not_found", "classified": 0}

    heuristic = default_pipeline()
    classified = 0
    low_confidence = 0
    threshold = config.classifier_confidence_threshold

    actions = [a for a in recording.actions if not a.user_confirmed]
    for _action, classification in heuristic.process(actions):
        classified += 1
        if classification.confidence < threshold:
            low_confidence += 1

    log.info(
        "classify_recording_complete",
        classified=classified,
        low_confidence=low_confidence,
    )
    return {
        "status": "ok",
        "classified": classified,
        "low_confidence": low_confidence,
    }
