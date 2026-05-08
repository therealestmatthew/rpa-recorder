"""Retention enforcement."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from rpa_recorder.medallion.bronze_store import LocalFilesystemStore
from rpa_recorder.medallion.retention import (
    RetentionConfig,
    enforce_retention,
)
from rpa_recorder.storage.db import BronzeArtifactRow, get_session
from rpa_recorder.storage.repositories import BronzeArtifactRepository


@pytest.fixture
def bronze_root(tmp_path: Path) -> Path:
    return tmp_path / "bronze"


@pytest.mark.asyncio
async def test_dry_run_reports_without_deleting(db_engine, bronze_root: Path) -> None:
    """`dry_run=True` reports what would be deleted but leaves files + rows alone."""
    store = LocalFilesystemStore(bronze_root)
    path = "runs/abc/attempts/old.png"
    await store.put(path, b"x")
    backdated = datetime.now(UTC) - timedelta(days=60)

    async with get_session(db_engine) as db:
        db.add(
            BronzeArtifactRow(
                id=str(uuid4()),
                kind="attempt_screenshot",
                path=path,
                created_at=backdated,
            )
        )
        await db.flush()

    config = RetentionConfig(windows_by_kind={"attempt_screenshot": 30})

    async with get_session(db_engine) as db:
        repo = BronzeArtifactRepository(db)
        report = await enforce_retention(store, repo, config, dry_run=True)

    assert report.dry_run is True
    assert path in report.deleted_paths
    assert (bronze_root / "runs" / "abc" / "attempts" / "old.png").exists()


@pytest.mark.asyncio
async def test_per_kind_windows_apply_independently(db_engine, bronze_root: Path) -> None:
    """Different `kind`s honour their own windows."""
    store = LocalFilesystemStore(bronze_root)
    old_kind_path = "old/screenshot.png"
    young_kind_path = "young/llm.json"
    await store.put(old_kind_path, b"a")
    await store.put(young_kind_path, b"b")
    now = datetime.now(UTC)

    async with get_session(db_engine) as db:
        db.add(
            BronzeArtifactRow(
                id=str(uuid4()),
                kind="attempt_screenshot",
                path=old_kind_path,
                created_at=now - timedelta(days=60),
            )
        )
        db.add(
            BronzeArtifactRow(
                id=str(uuid4()),
                kind="llm_call",
                path=young_kind_path,
                created_at=now - timedelta(days=60),
            )
        )
        await db.flush()

    config = RetentionConfig(
        windows_by_kind={"attempt_screenshot": 30, "llm_call": 365}
    )

    async with get_session(db_engine) as db:
        repo = BronzeArtifactRepository(db)
        report = await enforce_retention(store, repo, config, now=now)

    assert old_kind_path in report.deleted_paths
    assert young_kind_path in report.skipped_paths
    assert not (bronze_root / "old" / "screenshot.png").exists()
    assert (bronze_root / "young" / "llm.json").exists()


@pytest.mark.asyncio
async def test_unknown_kinds_are_kept(db_engine, bronze_root: Path) -> None:
    """A kind without a registered window is preserved."""
    store = LocalFilesystemStore(bronze_root)
    path = "future/data.bin"
    await store.put(path, b"x")
    backdated = datetime.now(UTC) - timedelta(days=10000)

    async with get_session(db_engine) as db:
        db.add(
            BronzeArtifactRow(
                id=str(uuid4()),
                kind="future_format",
                path=path,
                created_at=backdated,
            )
        )
        await db.flush()

    config = RetentionConfig(windows_by_kind={"attempt_screenshot": 30})

    async with get_session(db_engine) as db:
        repo = BronzeArtifactRepository(db)
        report = await enforce_retention(store, repo, config)

    assert report.deleted_paths == []
    assert path in report.skipped_paths
