"""Cold gold (DuckDB on Parquet) recompute."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pyarrow.parquet as pq
import pytest

from rpa_recorder.medallion.gold_cold import ColdGold
from rpa_recorder.storage.db import (
    LLMCallRow,
    RecordedActionRow,
    RecordingRow,
    get_session,
)


@pytest.fixture
def cold_root(tmp_path: Path) -> Path:
    return tmp_path / "gold_cold"


async def _seed_confirmed_action(db, *, rec_id: str, intent: str, label: str) -> None:
    db.add(
        RecordedActionRow(
            id=str(uuid4()),
            recording_id=rec_id,
            sequence=0,
            timestamp=datetime.now(UTC),
            action_type="click",
            url="https://example.com",
            semantic_intent=intent,
            user_label=label,
            user_confirmed=True,
            classification_confidence=0.9,
        )
    )
    await db.flush()


@pytest.mark.asyncio
async def test_classifier_accuracy_writes_parquet(db_engine, cold_root: Path) -> None:
    """Confirmed actions get a row each in classifier_accuracy.parquet."""
    rec_id = str(uuid4())
    async with get_session(db_engine) as db:
        db.add(
            RecordingRow(
                id=rec_id,
                name="t",
                created_at=datetime.now(UTC),
                starting_url="https://example.com",
            )
        )
        await db.flush()
        await _seed_confirmed_action(db, rec_id=rec_id, intent="navigate", label="navigate")
        await _seed_confirmed_action(db, rec_id=rec_id, intent="search", label="navigate")

    cold = ColdGold(cold_root)
    async with get_session(db_engine) as db:
        await cold.recompute_classifier_accuracy(db)

    target = cold_root / "classifier_accuracy.parquet"
    assert target.exists()
    table = pq.read_table(target)
    assert table.num_rows == 2
    assert "correct" in table.column_names


@pytest.mark.asyncio
async def test_llm_costs_daily_buckets_by_day(db_engine, cold_root: Path) -> None:
    """Two LLM calls on the same day produce one bucket; different days produce two."""
    async with get_session(db_engine) as db:
        for ts, in_tokens, out_tokens in [
            (datetime(2026, 5, 1, 9, 0, tzinfo=UTC), 100, 50),
            (datetime(2026, 5, 1, 14, 0, tzinfo=UTC), 200, 80),
            (datetime(2026, 5, 2, 9, 0, tzinfo=UTC), 50, 30),
        ]:
            db.add(
                LLMCallRow(
                    id=str(uuid4()),
                    called_for="classify",
                    model="claude-test",
                    prompt="p",
                    response="r",
                    input_tokens=in_tokens,
                    output_tokens=out_tokens,
                    latency_ms=100,
                    created_at=ts,
                )
            )
        await db.flush()

    cold = ColdGold(cold_root)
    async with get_session(db_engine) as db:
        await cold.recompute_llm_costs_daily(db)

    target = cold_root / "llm_costs_daily.parquet"
    table = pq.read_table(target)
    assert table.num_rows == 2
    rows = table.to_pylist()
    by_day = {row["day"].isoformat(): row for row in rows}
    assert by_day["2026-05-01"]["input_tokens"] == 300
    assert by_day["2026-05-01"]["output_tokens"] == 130
    assert by_day["2026-05-02"]["calls"] == 1


@pytest.mark.asyncio
async def test_replay_scripts_parquet_per_recording(db_engine, cold_root: Path) -> None:
    """One replay-script Parquet per recording, sequenced by action."""
    rec_id_str = str(uuid4())
    async with get_session(db_engine) as db:
        db.add(
            RecordingRow(
                id=rec_id_str,
                name="t",
                created_at=datetime.now(UTC),
                starting_url="https://example.com",
            )
        )
        await db.flush()
        for i in range(3):
            db.add(
                RecordedActionRow(
                    id=str(uuid4()),
                    recording_id=rec_id_str,
                    sequence=i,
                    timestamp=datetime.now(UTC),
                    action_type="click",
                    url=f"https://example.com/{i}",
                    semantic_intent="navigate",
                    user_confirmed=(i % 2 == 0),
                ),
            )
        await db.flush()

    cold = ColdGold(cold_root)
    from uuid import UUID  # noqa: PLC0415
    async with get_session(db_engine) as db:
        await cold.recompute_replay_scripts(db, UUID(rec_id_str))

    target = cold_root / "replay_scripts" / f"{rec_id_str}.parquet"
    assert target.exists()
    table = pq.read_table(target)
    assert table.num_rows == 3
    assert list(table.column("sequence").to_pylist()) == [0, 1, 2]


def test_query_returns_arrow_table(cold_root: Path) -> None:
    """`ColdGold.query()` runs a one-shot DuckDB query."""
    cold = ColdGold(cold_root)
    table = cold.query("SELECT 1 AS one")
    assert table.num_rows == 1
    assert table.column("one")[0].as_py() == 1
