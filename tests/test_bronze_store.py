"""Tests for `LocalFilesystemStore` (the v1 `BronzeStore` implementation)."""

import hashlib
from pathlib import Path
from typing import Any

import aiofiles
import pytest

from rpa_recorder.medallion.bronze_store import LocalFilesystemStore


class TestPutAndGet:
    async def test_round_trip_returns_sha256(self, tmp_path: Path) -> None:
        store = LocalFilesystemStore(tmp_path)
        data = b"hello world"
        sha = await store.put("recordings/x/payload.bin", data)
        assert sha == hashlib.sha256(data).hexdigest()
        loaded = await store.get("recordings/x/payload.bin")
        assert loaded == data

    async def test_atomic_put_does_not_clobber_on_crash(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = LocalFilesystemStore(tmp_path)
        rel = "recordings/x/file.bin"
        # Pre-write target with original content.
        await store.put(rel, b"original")
        # Monkeypatch Path.replace to fail.
        original_replace = Path.replace

        def boom(self: Path, target: str | Path) -> Path:
            raise RuntimeError("simulated rename failure")

        monkeypatch.setattr(Path, "replace", boom)
        with pytest.raises(RuntimeError):
            await store.put(rel, b"new content")
        # Restore for assertions.
        monkeypatch.setattr(Path, "replace", original_replace)

        target = tmp_path / "recordings" / "x" / "file.bin"
        tmp = tmp_path / "recordings" / "x" / "file.bin.tmp"
        assert target.read_bytes() == b"original"
        assert not tmp.exists()


class TestAppend:
    async def test_append_line_writes_newline_terminated(self, tmp_path: Path) -> None:
        store = LocalFilesystemStore(tmp_path)
        rel = "recordings/y/events.jsonl"
        await store.append_line(rel, "first")
        await store.append_line(rel, "second")
        await store.append_line(rel, "third")
        target = tmp_path / "recordings" / "y" / "events.jsonl"
        assert target.read_text(encoding="utf-8") == "first\nsecond\nthird\n"

    async def test_append_lines_writes_batch_in_one_open(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = LocalFilesystemStore(tmp_path)
        rel = "recordings/z/events.jsonl"
        # Touch the directory so the count below only includes the appends.
        (tmp_path / "recordings" / "z").mkdir(parents=True, exist_ok=True)

        open_calls = 0
        original_open = aiofiles.open

        def counting_open(*args: Any, **kwargs: Any) -> Any:
            nonlocal open_calls
            open_calls += 1
            return original_open(*args, **kwargs)

        monkeypatch.setattr(aiofiles, "open", counting_open)
        await store.append_lines(rel, ["a", "b", "c", "d", "e"])
        assert open_calls == 1
        target = tmp_path / "recordings" / "z" / "events.jsonl"
        assert target.read_text(encoding="utf-8") == "a\nb\nc\nd\ne\n"

    async def test_append_lines_empty_is_noop(self, tmp_path: Path) -> None:
        store = LocalFilesystemStore(tmp_path)
        await store.append_lines("recordings/empty/file.jsonl", [])
        assert not (tmp_path / "recordings" / "empty" / "file.jsonl").exists()


class TestDelete:
    async def test_delete_is_idempotent(self, tmp_path: Path) -> None:
        store = LocalFilesystemStore(tmp_path)
        rel = "recordings/q/file.bin"
        await store.put(rel, b"x")
        await store.delete(rel)
        # Second delete must not raise.
        await store.delete(rel)
        assert not (tmp_path / "recordings" / "q" / "file.bin").exists()


class TestStat:
    async def test_returns_size_and_digest(self, tmp_path: Path) -> None:
        store = LocalFilesystemStore(tmp_path)
        rel = "recordings/r/file.bin"
        payload = b"x" * 1024
        await store.put(rel, payload)
        size, sha = await store.stat(rel)
        assert size == 1024
        assert sha == hashlib.sha256(payload).hexdigest()


class TestList:
    async def test_list_returns_only_under_prefix(self, tmp_path: Path) -> None:
        store = LocalFilesystemStore(tmp_path)
        await store.put("recordings/a/x.bin", b"1")
        await store.put("recordings/b/y.bin", b"2")
        await store.put("runs/r1/attempts/a1/screenshot.png", b"3")

        rec_files = await store.list("recordings/")
        run_files = await store.list("runs/")
        assert rec_files == ["recordings/a/x.bin", "recordings/b/y.bin"]
        assert run_files == ["runs/r1/attempts/a1/screenshot.png"]

    async def test_list_returns_empty_for_missing_prefix(self, tmp_path: Path) -> None:
        store = LocalFilesystemStore(tmp_path)
        assert await store.list("nonexistent/") == []
