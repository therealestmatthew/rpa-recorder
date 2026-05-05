"""Integration tests for the recorder + executor bronze write paths.

The whole file is marked `@pytest.mark.integration`; some tests run a real
Chromium via `BrowserSession`, others exercise the bronze queue directly
without a browser, but they share the milestone's marker for grouping.
"""

import asyncio
import json
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import aiofiles
import pytest
import structlog.testing

from rpa_recorder.browser.executor import Executor
from rpa_recorder.browser.recorder import Recorder
from rpa_recorder.browser.session import BrowserSession
from rpa_recorder.medallion import paths as bronze_paths
from rpa_recorder.medallion.bronze import BronzeWriter
from rpa_recorder.medallion.bronze_store import LocalFilesystemStore
from rpa_recorder.models import (
    ActionType,
    ClickPayload,
    ElementSelector,
    RecordedAction,
    Recording,
)
from rpa_recorder.storage.db import create_engine, get_session, init_db
from rpa_recorder.storage.repositories import BronzeArtifactRepository

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncEngine

# Suppress aiosqlite's connection deallocator ResourceWarning. The connection
# closes asynchronously via a worker thread; under pytest's filterwarnings=error
# the late-firing warning gets attributed to whichever test happens to be running
# when GC kicks in, producing flaky failures unrelated to the test logic.
pytestmark = [
    pytest.mark.integration,
    pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning"),
]


# ---------- Setup helpers ----------


async def _setup_engine(tmp_path: Path) -> AsyncEngine:
    db = tmp_path / "rpa.db"
    engine = create_engine(f"sqlite+aiosqlite:///{db}")
    await init_db(engine)
    return engine


@asynccontextmanager
async def _writer_for(
    tmp_path: Path,
) -> AsyncIterator[tuple[BronzeWriter, AsyncEngine, LocalFilesystemStore]]:
    """Yield a BronzeWriter wired to a fresh DB + filesystem store."""
    engine = await _setup_engine(tmp_path)
    store = LocalFilesystemStore(tmp_path / "bronze")
    try:
        async with get_session(engine) as session:
            repo = BronzeArtifactRepository(session)
            yield BronzeWriter(store, repo), engine, store
    finally:
        await engine.dispose()


_FIXTURE_HTML = """<!doctype html>
<html lang="en">
  <head><title>Bronze fixture</title></head>
  <body>
    <button id="save" data-testid="save-btn" aria-label="Save" type="button">Save</button>
  </body>
</html>
"""


def _write_fixture(tmp_path: Path) -> str:
    page = tmp_path / "fixture.html"
    page.write_text(_FIXTURE_HTML, encoding="utf-8")
    return page.as_uri()


# ---------- Recorder + bronze ----------


class TestRecorderBronzeWrites:
    async def test_recorder_appends_envelope_to_bronze(self, tmp_path: Path) -> None:
        fixture_url = _write_fixture(tmp_path)
        rec_id = uuid4()
        async with _writer_for(tmp_path) as (writer, _engine, store):
            async with BrowserSession(headless=True) as session:
                recorder = Recorder(
                    session.page,
                    name="bronze-click",
                    bronze=writer,
                    recording_id=rec_id,
                )
                await recorder.start()
                await session.page.goto(fixture_url)
                await session.page.click("#save")
                await session.page.wait_for_function(
                    "() => (window.__rpaCaptureCount || 0) >= 1",
                    timeout=5000,
                )
                await recorder.stop()

            jsonl_rel = bronze_paths.recording_events_jsonl(rec_id)
            content = await store.get(jsonl_rel)
            lines = [line for line in content.decode("utf-8").split("\n") if line]
            assert lines, "expected at least one envelope in bronze JSONL"
            click_lines = [json.loads(line) for line in lines]
            assert any(env.get("event_type") == "click" for env in click_lines)

    async def test_drain_task_starts_and_stops_cleanly(self, tmp_path: Path) -> None:
        async with (
            _writer_for(tmp_path) as (writer, _engine, _store),
            BrowserSession(headless=True) as session,
        ):
            recorder = Recorder(
                session.page,
                bronze=writer,
                recording_id=uuid4(),
            )
            await recorder.start()
            assert recorder._bronze_drain_task is not None
            assert not recorder._bronze_drain_task.done()
            await recorder.stop()
            assert recorder._bronze_drain_task.done()

    async def test_bronze_write_failure_does_not_break_recording(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fixture_url = _write_fixture(tmp_path)
        rec_id = uuid4()
        async with _writer_for(tmp_path) as (writer, _engine, _store):

            async def boom(*_args: object, **_kwargs: object) -> None:
                raise RuntimeError("simulated bronze failure")

            monkeypatch.setattr(writer, "append_events", boom)

            async with BrowserSession(headless=True) as session:
                recorder = Recorder(
                    session.page,
                    name="failing-bronze",
                    bronze=writer,
                    recording_id=rec_id,
                )
                await recorder.start()
                await session.page.goto(fixture_url)
                await session.page.click("#save")
                await session.page.wait_for_function(
                    "() => (window.__rpaCaptureCount || 0) >= 1",
                    timeout=5000,
                )
                await recorder.stop()
                rec = recorder.get_recording()

            # Recording still completed; silver actions captured in memory.
            assert any(a.action_type == ActionType.CLICK for a in rec.actions)


# ---------- Executor + bronze ----------


def _make_recording(actions: list[RecordedAction], starting_url: str) -> Recording:
    return Recording(
        name="bronze-exec",
        created_at=datetime.now(UTC),
        starting_url=starting_url,
        actions=actions,
    )


def _click_action(selector: ElementSelector, *, sequence: int = 1) -> RecordedAction:
    return RecordedAction(
        sequence=sequence,
        timestamp=datetime.now(UTC),
        action_type=ActionType.CLICK,
        payload=ClickPayload(button="left"),
        selector=selector,
        url="about:blank",
    )


class TestExecutorBronzeWrites:
    async def test_executor_failure_writes_attempt_artifacts(self, tmp_path: Path) -> None:
        fixture_url = _write_fixture(tmp_path)
        recording = _make_recording(
            [_click_action(ElementSelector(test_id="does-not-exist"))],
            starting_url=fixture_url,
        )
        async with _writer_for(tmp_path) as (writer, engine, store):
            async with BrowserSession(headless=True) as session:
                await session.page.goto(fixture_url)
                executor = Executor(session.page, recording, bronze=writer)
                result = await executor.run()
                run_id = executor.run_id

            attempt = result.executions[0].attempts[0]
            assert attempt.screenshot_path is not None
            assert attempt.screenshot_path.startswith(f"runs/{run_id}/attempts/")
            assert attempt.screenshot_path.endswith("/screenshot.png")
            assert attempt.dom_snapshot_path is not None
            assert attempt.dom_snapshot_path.endswith("/dom.html")

            # Files exist on disk.
            ss_data = await store.get(attempt.screenshot_path)
            assert len(ss_data) > 0

        # Outside the writer's session: re-open and check pointer rows.
        async with get_session(engine) as session:
            repo = BronzeArtifactRepository(session)
            rows = await repo.list_for_attempt(attempt.id)
        kinds = {r.kind for r in rows}
        assert "screenshot" in kinds
        assert "dom" in kinds
        assert all(r.attempt_id == str(attempt.id) for r in rows)
        assert all(r.run_id == str(run_id) for r in rows)


# ---------- Session __aexit__ HAR + trace handoff ----------


class TestSessionFinalize:
    async def test_finalize_recording_writes_har_and_trace(self, tmp_path: Path) -> None:
        rec_id = uuid4()
        har_path = tmp_path / "network.har"
        trace_path = tmp_path / "trace.zip"
        async with _writer_for(tmp_path) as (writer, engine, store):
            async with BrowserSession(
                headless=True,
                har_path=str(har_path),
                trace_path=str(trace_path),
                bronze=writer,
                recording_id=rec_id,
            ) as session:
                await session.page.goto("about:blank")

            har_rel = bronze_paths.recording_har(rec_id)
            trace_rel = bronze_paths.recording_trace(rec_id)
            har_bytes = await store.get(har_rel)
            trace_bytes = await store.get(trace_rel)
            assert len(har_bytes) > 0
            assert len(trace_bytes) > 0

        async with get_session(engine) as session:
            repo = BronzeArtifactRepository(session)
            rows = await repo.list_for_recording(rec_id)
        kinds = {r.kind for r in rows}
        assert "har" in kinds
        assert "trace" in kinds


# ---------- Queue / drain semantics (no browser needed) ----------


class _StubPage:
    """Minimum surface needed to construct a `Recorder` without Playwright."""

    url: str = "about:blank"


class _NullRepo:
    """No-op stand-in for `BronzeArtifactRepository` — avoids aiosqlite in queue tests."""

    async def add(self, **_kwargs: Any) -> None:
        return

    async def update_size_and_sha(self, **_kwargs: Any) -> None:
        return


def _make_envelope(idx: int) -> dict[str, Any]:
    return {
        "event_type": "click",
        "target": {
            "tag": "button",
            "is_visible": True,
            "is_enabled": True,
        },
        "payload": {"button": "left", "modifiers": []},
        "frame_url": "https://example.com/page",
        "page_title": f"page-{idx}",
        "timestamp_ms": 0,
        "viewport": {"width": 1280, "height": 800},
    }


def _stub_writer(tmp_path: Path) -> BronzeWriter:
    """BronzeWriter wired to a local fs store and a no-op repo (no aiosqlite)."""
    return BronzeWriter(
        LocalFilesystemStore(tmp_path / "bronze"),
        _NullRepo(),  # type: ignore[arg-type]
    )


def _make_recorder_for_queue_test(writer: BronzeWriter, *, queue_size: int = 1000) -> Recorder:
    rec = Recorder(
        _StubPage(),  # type: ignore[arg-type]
        bronze=writer,
        recording_id=uuid4(),
        bronze_queue_size=queue_size,
    )
    rec._bronze_queue = asyncio.Queue(maxsize=queue_size)
    return rec


class TestQueueSemantics:
    async def test_recorder_under_load_does_not_block_capture(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        writer = _stub_writer(tmp_path)

        async def slow_append(*_args: object, **_kwargs: object) -> None:
            await asyncio.sleep(0.1)

        monkeypatch.setattr(writer, "append_events", slow_append)

        recorder = _make_recorder_for_queue_test(writer, queue_size=2000)
        start = time.monotonic()
        for i in range(1000):
            await recorder._on_capture(_make_envelope(i))
        elapsed = time.monotonic() - start
        assert elapsed < 1.0, f"capture path too slow: {elapsed:.3f}s for 1000 events"

    async def test_recorder_drops_with_warning_when_queue_full(self, tmp_path: Path) -> None:
        writer = _stub_writer(tmp_path)
        recorder = _make_recorder_for_queue_test(writer, queue_size=10)
        with structlog.testing.capture_logs() as captured:
            for i in range(100):
                await recorder._on_capture(_make_envelope(i))
        drops = [e for e in captured if e.get("event") == "bronze_queue_full_dropped"]
        assert len(drops) >= 80, f"expected ~90 drops, got {len(drops)}"
        for drop in drops:
            assert drop["event_type"] == "click"
            assert drop["frame_url"] == "https://example.com/page"

    async def test_drain_batches_amortize_io(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        writer = _stub_writer(tmp_path)
        open_calls = 0
        original_open = aiofiles.open

        def counting_open(*args: Any, **kwargs: Any) -> Any:
            nonlocal open_calls
            open_calls += 1
            return original_open(*args, **kwargs)

        monkeypatch.setattr(aiofiles, "open", counting_open)

        recorder = _make_recorder_for_queue_test(writer, queue_size=200)
        drain_task = asyncio.create_task(recorder._drain_bronze())
        recorder._bronze_drain_task = drain_task

        for i in range(30):
            await recorder._on_capture(_make_envelope(i))

        # Allow the drain task to consume the queue and flush its batches.
        queue = recorder._bronze_queue
        assert queue is not None
        await asyncio.sleep(0.2)

        # Stop the drain task cleanly.
        queue.put_nowait(None)
        await asyncio.wait_for(drain_task, timeout=2.0)

        assert open_calls < 5, f"expected <5 file opens, got {open_calls}"

    async def test_recorder_drains_remaining_on_stop(self, tmp_path: Path) -> None:
        async with (
            _writer_for(tmp_path) as (writer, _engine, store),
            BrowserSession(headless=True) as session,
        ):
            rec_id = uuid4()
            recorder = Recorder(
                session.page,
                bronze=writer,
                recording_id=rec_id,
            )
            await recorder.start()
            for i in range(50):
                await recorder._on_capture(_make_envelope(i))
            await recorder.stop()

            jsonl_rel = bronze_paths.recording_events_jsonl(rec_id)
            content = await store.get(jsonl_rel)
            lines = [line for line in content.decode("utf-8").split("\n") if line]
            # We pumped 50 directly via _on_capture; some Playwright-emitted
            # navigations may have added more, so we assert >= 50.
            assert len(lines) >= 50
