"""Silver promotion: bronze JSONL → RecordedActionRow."""

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from rpa_recorder.medallion import paths
from rpa_recorder.medallion.bronze_store import LocalFilesystemStore
from rpa_recorder.medallion.silver import promote_bronze_to_silver
from rpa_recorder.storage.db import RecordedActionRow, RecordingRow, get_session


def _click_envelope(seq: int, label: str) -> dict[str, object]:
    return {
        "event_type": "click",
        "timestamp_ms": 1715000000000 + seq * 100,
        "url": "https://example.com",
        "frame_url": "https://example.com",
        "page_title": "Example",
        "target": {
            "tag": "button",
            "role": "button",
            "accessible_name": label,
            "css": f"button[data-id='{seq}']",
        },
        "payload": {"button": "left", "modifiers": []},
    }


@pytest.fixture
def bronze_root(tmp_path: Path) -> Path:
    return tmp_path / "bronze"


@pytest.mark.asyncio
async def test_silver_promotes_envelopes_into_rows(db_engine, bronze_root: Path) -> None:
    """Three envelopes in JSONL become three `RecordedActionRow` rows."""
    rec_id = uuid4()
    store = LocalFilesystemStore(bronze_root)
    jsonl = paths.recording_events_jsonl(rec_id)
    await store.append_lines(
        jsonl,
        [json.dumps(_click_envelope(i, f"button {i}")) for i in range(3)],
    )

    async with get_session(db_engine) as db:
        db.add(
            RecordingRow(
                id=str(rec_id),
                name="t",
                created_at=datetime.now(UTC),
                starting_url="https://example.com",
            ),
        )
        await db.flush()
        inserted = await promote_bronze_to_silver(db, store, rec_id)

    assert inserted == 3
    async with get_session(db_engine) as db:
        count = (
            await db.execute(
                select(func.count(RecordedActionRow.id)).where(
                    RecordedActionRow.recording_id == str(rec_id),
                )
            )
        ).scalar_one()
    assert count == 3


@pytest.mark.asyncio
async def test_silver_is_idempotent(db_engine, bronze_root: Path) -> None:
    """Running silver twice inserts zero rows the second time."""
    rec_id = uuid4()
    store = LocalFilesystemStore(bronze_root)
    await store.append_lines(
        paths.recording_events_jsonl(rec_id),
        [json.dumps(_click_envelope(i, f"b{i}")) for i in range(2)],
    )

    async with get_session(db_engine) as db:
        db.add(
            RecordingRow(
                id=str(rec_id),
                name="t",
                created_at=datetime.now(UTC),
                starting_url="https://example.com",
            ),
        )
        await db.flush()
        first = await promote_bronze_to_silver(db, store, rec_id)
    async with get_session(db_engine) as db:
        second = await promote_bronze_to_silver(db, store, rec_id)

    assert first == 2
    assert second == 0


@pytest.mark.asyncio
async def test_silver_skips_malformed_lines(db_engine, bronze_root: Path) -> None:
    """A non-JSON line is skipped; the rest still get inserted."""
    rec_id = uuid4()
    store = LocalFilesystemStore(bronze_root)
    await store.append_lines(
        paths.recording_events_jsonl(rec_id),
        [
            json.dumps(_click_envelope(0, "ok")),
            "not-json-at-all",
            json.dumps(_click_envelope(1, "ok2")),
        ],
    )

    async with get_session(db_engine) as db:
        db.add(
            RecordingRow(
                id=str(rec_id),
                name="t",
                created_at=datetime.now(UTC),
                starting_url="https://example.com",
            ),
        )
        await db.flush()
        inserted = await promote_bronze_to_silver(db, store, rec_id)

    assert inserted == 2


@pytest.mark.asyncio
async def test_silver_returns_zero_when_no_jsonl(db_engine, bronze_root: Path) -> None:
    """Missing JSONL is not an error — silver no-ops."""
    rec_id = uuid4()
    store = LocalFilesystemStore(bronze_root)

    async with get_session(db_engine) as db:
        db.add(
            RecordingRow(
                id=str(rec_id),
                name="t",
                created_at=datetime.now(UTC),
                starting_url="https://example.com",
            ),
        )
        await db.flush()
        inserted = await promote_bronze_to_silver(db, store, rec_id)

    assert inserted == 0
