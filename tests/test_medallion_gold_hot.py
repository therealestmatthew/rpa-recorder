"""Hot gold recompute: per-recording metrics + dashboard."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from rpa_recorder.medallion.gold_hot import recompute_gold_hot
from rpa_recorder.storage.db import (
    RecordedActionRow,
    RecordingRow,
    RunResultRow,
    get_session,
)
from rpa_recorder.storage.repositories import GoldHotRepository


async def _seed_recording(db, *, rec_id: str, n_actions: int = 0) -> None:
    db.add(
        RecordingRow(
            id=rec_id,
            name="t",
            created_at=datetime.now(UTC),
            starting_url="https://example.com",
        )
    )
    for i in range(n_actions):
        db.add(
            RecordedActionRow(
                id=str(uuid4()),
                recording_id=rec_id,
                sequence=i,
                timestamp=datetime.now(UTC),
                action_type="click",
                url="https://example.com",
                semantic_intent="navigate",
                classification_confidence=0.8 + i * 0.01,
            ),
        )
    await db.flush()


async def _seed_run(
    db, *, rec_id: str, status: str, started: datetime, duration_ms: int = 1000
) -> str:
    run_id = str(uuid4())
    db.add(
        RunResultRow(
            id=run_id,
            recording_id=rec_id,
            started_at=started,
            ended_at=started + timedelta(milliseconds=duration_ms),
            status=status,
        )
    )
    await db.flush()
    return run_id


@pytest.mark.asyncio
async def test_recompute_idempotent(db_engine) -> None:
    """Calling recompute twice leaves row count stable; computed_at advances."""
    rec_id = str(uuid4())
    async with get_session(db_engine) as db:
        await _seed_recording(db, rec_id=rec_id, n_actions=2)
        await _seed_run(db, rec_id=rec_id, status="success", started=datetime.now(UTC))

    async with get_session(db_engine) as db:
        await recompute_gold_hot(db)
    async with get_session(db_engine) as db:
        repo = GoldHotRepository(db)
        first = await repo.get_recording_metrics(rec_id)
    first_computed = first.computed_at if first else None

    async with get_session(db_engine) as db:
        await recompute_gold_hot(db)
    async with get_session(db_engine) as db:
        repo = GoldHotRepository(db)
        second = await repo.get_recording_metrics(rec_id)

    assert first is not None
    assert second is not None
    assert first.recording_id == second.recording_id
    assert second.computed_at >= (first_computed or datetime.now(UTC))


@pytest.mark.asyncio
async def test_success_rate_aggregates_correctly(db_engine) -> None:
    """3 runs (2 success + 1 failed) produce success_rate=2/3."""
    rec_id = str(uuid4())
    started = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)
    async with get_session(db_engine) as db:
        await _seed_recording(db, rec_id=rec_id)
        await _seed_run(db, rec_id=rec_id, status="success", started=started)
        await _seed_run(db, rec_id=rec_id, status="success", started=started)
        await _seed_run(db, rec_id=rec_id, status="failed", started=started)

    async with get_session(db_engine) as db:
        await recompute_gold_hot(db)
    async with get_session(db_engine) as db:
        repo = GoldHotRepository(db)
        metrics = await repo.get_recording_metrics(rec_id)

    assert metrics is not None
    assert metrics.total_runs == 3
    assert abs(metrics.success_rate - (2 / 3)) < 1e-9


@pytest.mark.asyncio
async def test_dashboard_buckets_by_date(db_engine) -> None:
    """Runs on different days produce separate dashboard rows."""
    rec_id = str(uuid4())
    async with get_session(db_engine) as db:
        await _seed_recording(db, rec_id=rec_id)
        await _seed_run(
            db,
            rec_id=rec_id,
            status="success",
            started=datetime(2026, 5, 1, 8, 0, tzinfo=UTC),
        )
        await _seed_run(
            db,
            rec_id=rec_id,
            status="recovered",
            started=datetime(2026, 5, 2, 8, 0, tzinfo=UTC),
        )

    async with get_session(db_engine) as db:
        await recompute_gold_hot(db)
    async with get_session(db_engine) as db:
        repo = GoldHotRepository(db)
        rows = await repo.list_dashboard_rows()

    assert len(rows) == 2
    by_date = {row.date.isoformat(): row for row in rows}
    assert by_date["2026-05-01"].runs_success == 1
    assert by_date["2026-05-02"].runs_recovered == 1
