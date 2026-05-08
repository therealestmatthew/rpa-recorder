"""Hot gold recompute (M11.5).

Pulls aggregates from silver and writes them to `gold_recording_metrics`
and `gold_run_dashboard` via `GoldHotRepository`. Idempotent (upsert on
PK). Hourly cron + on-demand from the M11 confirmation flow and the
M12 `/medallion/recompute` endpoint.
"""

from collections import defaultdict
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import func, select

from rpa_recorder.storage.db import (
    RecordedActionRow,
    RecordingRow,
    RunResultRow,
)
from rpa_recorder.storage.repositories import GoldHotRepository

if TYPE_CHECKING:
    from datetime import date
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

_log = structlog.get_logger(__name__)


_SUCCESS_STATUSES = {"success", "recovered"}


async def _compute_recording_metrics(
    session: AsyncSession,
    recording_id: str,
    *,
    computed_at: datetime,
) -> dict[str, object]:
    runs = list(
        (
            await session.execute(
                select(RunResultRow).where(RunResultRow.recording_id == recording_id)
            )
        ).scalars()
    )
    total_runs = len(runs)
    if total_runs == 0:
        confidence = (
            await session.execute(
                select(func.coalesce(func.avg(RecordedActionRow.classification_confidence), 0.0)).where(
                    RecordedActionRow.recording_id == recording_id
                )
            )
        ).scalar_one()
        return {
            "recording_id": recording_id,
            "total_runs": 0,
            "success_rate": 0.0,
            "avg_duration_ms": 0,
            "classifier_confidence_avg": float(confidence or 0.0),
            "last_replayed_at": None,
            "computed_at": computed_at,
        }

    successes = sum(1 for r in runs if r.status in _SUCCESS_STATUSES)
    durations: list[int] = []
    last_replayed_at: datetime | None = None
    for r in runs:
        if r.started_at is not None and r.ended_at is not None:
            durations.append(int((r.ended_at - r.started_at).total_seconds() * 1000))
        ended = r.ended_at or r.started_at
        if ended is not None and (last_replayed_at is None or ended > last_replayed_at):
            last_replayed_at = ended
    avg_duration = int(sum(durations) / len(durations)) if durations else 0

    confidence = (
        await session.execute(
            select(func.coalesce(func.avg(RecordedActionRow.classification_confidence), 0.0)).where(
                RecordedActionRow.recording_id == recording_id
            )
        )
    ).scalar_one()

    return {
        "recording_id": recording_id,
        "total_runs": total_runs,
        "success_rate": successes / total_runs,
        "avg_duration_ms": avg_duration,
        "classifier_confidence_avg": float(confidence or 0.0),
        "last_replayed_at": last_replayed_at,
        "computed_at": computed_at,
    }


def _bucket_run_dashboards(
    runs: list[RunResultRow],
) -> dict[tuple[date, str], dict[str, int]]:
    buckets: dict[tuple[date, str], dict[str, int]] = defaultdict(
        lambda: {"runs_total": 0, "runs_success": 0, "runs_failed": 0, "runs_recovered": 0}
    )
    for r in runs:
        ended = r.ended_at or r.started_at
        ended_utc = ended.astimezone(UTC) if ended.tzinfo else ended.replace(tzinfo=UTC)
        bucket = buckets[(ended_utc.date(), r.recording_id)]
        bucket["runs_total"] += 1
        if r.status == "success":
            bucket["runs_success"] += 1
        elif r.status == "recovered":
            bucket["runs_recovered"] += 1
        elif r.status == "failed":
            bucket["runs_failed"] += 1
    return buckets


async def recompute_gold_hot(
    session: AsyncSession,
    *,
    recording_id: UUID | None = None,
) -> int:
    """Recompute hot gold tables. Returns the number of upserts performed.

    `recording_id=None` means "all recordings" (cron path). Pass a
    specific UUID to limit recompute to one recording (on-demand path).
    """
    repo = GoldHotRepository(session)
    computed_at = datetime.now(UTC)

    if recording_id is None:
        recording_ids = list(
            (await session.execute(select(RecordingRow.id))).scalars()
        )
    else:
        recording_ids = [str(recording_id)]

    upserts = 0
    for rec_id in recording_ids:
        metrics = await _compute_recording_metrics(
            session, rec_id, computed_at=computed_at
        )
        await repo.upsert_recording_metrics(**metrics)  # type: ignore[arg-type]
        upserts += 1

    if recording_id is None:
        runs = list(
            (await session.execute(select(RunResultRow))).scalars()
        )
    else:
        runs = list(
            (
                await session.execute(
                    select(RunResultRow).where(RunResultRow.recording_id == str(recording_id))
                )
            ).scalars()
        )
    buckets = _bucket_run_dashboards(runs)
    for (run_date, rec_id), counts in buckets.items():
        await repo.upsert_run_dashboard_row(
            run_date=run_date,
            recording_id=rec_id,
            runs_total=counts["runs_total"],
            runs_success=counts["runs_success"],
            runs_failed=counts["runs_failed"],
            runs_recovered=counts["runs_recovered"],
            computed_at=computed_at,
        )
        upserts += 1

    return upserts


__all__ = ["recompute_gold_hot"]
