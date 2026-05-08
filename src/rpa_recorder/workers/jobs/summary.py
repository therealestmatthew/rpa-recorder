"""ARQ `generate_run_summary` job — placeholder summary generator.

Loads the run, computes a one-line summary, persists it on
`RunResultRow.summary`. The actual summarization template lives in
`storage/repositories.py:RunResultRepository`. Kept thin so the cron
schedule and replay-completion fanout have a stable hook to call.
"""

from typing import Any
from uuid import UUID

import structlog

_log = structlog.get_logger(__name__)


async def generate_run_summary(
    ctx: dict[str, Any],
    *,
    run_id: str,
) -> dict[str, Any]:
    """Compute and persist a textual summary for a completed run."""
    from rpa_recorder.storage.db import RunResultRow, get_session  # noqa: PLC0415

    engine = ctx["db_engine"]
    log = _log.bind(run_id=run_id, job_id=ctx.get("job_id"))

    async with get_session(engine) as db:
        row = await db.get(RunResultRow, str(UUID(run_id)))
        if row is None:
            log.warning("summary_run_not_found")
            return {"status": "not_found"}
        succeeded = sum(1 for ex in row.executions if ex.status in ("success", "recovered"))
        failed = sum(1 for ex in row.executions if ex.status == "failed")
        row.summary = (
            f"{row.status} — {succeeded} succeeded, {failed} failed of "
            f"{len(row.executions)} actions"
        )
        await db.flush()

    log.info("summary_written")
    return {"status": "ok", "succeeded": succeeded, "failed": failed}
