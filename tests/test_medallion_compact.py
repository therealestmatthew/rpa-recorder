"""Bronze JSONL → Parquet compaction."""

import json
from pathlib import Path
from uuid import uuid4

import pyarrow.parquet as pq
import pytest

from rpa_recorder.medallion import paths
from rpa_recorder.medallion.bronze_store import LocalFilesystemStore
from rpa_recorder.medallion.compact import (
    compact_all_recordings,
    compact_recording_jsonl_to_parquet,
)
from rpa_recorder.storage.db import get_session
from rpa_recorder.storage.repositories import BronzeArtifactRepository


@pytest.fixture
def bronze_root(tmp_path: Path) -> Path:
    return tmp_path / "bronze"


@pytest.mark.asyncio
async def test_compact_writes_parquet_with_matching_row_count(
    db_engine, bronze_root: Path
) -> None:
    """N envelopes in JSONL → Parquet with N rows."""
    rec_id = uuid4()
    store = LocalFilesystemStore(bronze_root)
    envelopes = [{"event_type": "click", "url": f"https://e/{i}"} for i in range(5)]
    await store.append_lines(
        paths.recording_events_jsonl(rec_id),
        [json.dumps(e) for e in envelopes],
    )

    async with get_session(db_engine) as db:
        repo = BronzeArtifactRepository(db)
        result = await compact_recording_jsonl_to_parquet(
            store, repo, rec_id, parquet_root=bronze_root,
        )

    assert result == paths.recording_events_parquet(rec_id)
    parquet_path = bronze_root / "recordings" / str(rec_id) / "raw_events.parquet"
    assert parquet_path.exists()
    table = pq.read_table(parquet_path)
    assert table.num_rows == 5
    assert "envelope_json" in table.column_names


@pytest.mark.asyncio
async def test_compact_is_idempotent(db_engine, bronze_root: Path) -> None:
    """A second run with unchanged JSONL doesn't re-write the Parquet artifact row."""
    rec_id = uuid4()
    store = LocalFilesystemStore(bronze_root)
    await store.append_lines(
        paths.recording_events_jsonl(rec_id),
        [json.dumps({"event_type": "click", "url": "https://e/0"})],
    )

    async with get_session(db_engine) as db:
        repo = BronzeArtifactRepository(db)
        await compact_recording_jsonl_to_parquet(
            store, repo, rec_id, parquet_root=bronze_root,
        )
    async with get_session(db_engine) as db:
        repo = BronzeArtifactRepository(db)
        first_artifacts = await repo.list_for_recording(rec_id)
    async with get_session(db_engine) as db:
        repo = BronzeArtifactRepository(db)
        second_result = await compact_recording_jsonl_to_parquet(
            store, repo, rec_id, parquet_root=bronze_root,
        )
        second_artifacts = await repo.list_for_recording(rec_id)

    assert second_result == paths.recording_events_parquet(rec_id)
    assert len([a for a in first_artifacts if a.kind == "event_parquet"]) == 1
    assert len([a for a in second_artifacts if a.kind == "event_parquet"]) == 1


@pytest.mark.asyncio
async def test_compact_all_skips_missing_jsonl(db_engine, bronze_root: Path) -> None:
    """A recording dir without raw_events.jsonl is skipped silently."""
    rec_id = uuid4()
    store = LocalFilesystemStore(bronze_root)
    await store.put(
        f"recordings/{rec_id}/network.har",
        b'{"placeholder": true}',
    )

    async with get_session(db_engine) as db:
        repo = BronzeArtifactRepository(db)
        written = await compact_all_recordings(
            store, repo, parquet_root=bronze_root,
        )

    assert written == []
