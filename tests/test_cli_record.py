"""Tests for `rpa record`.

The integration variant (against a real browser) is gated behind
`@pytest.mark.integration`. The unit tests below patch out `BrowserSession`,
`Recorder`, and the wait-loop so the command body runs end-to-end without
spinning up Playwright.
"""

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from typer.testing import CliRunner

from rpa_recorder.cli import dependencies
from rpa_recorder.cli.app import app
from rpa_recorder.cli.commands import record as record_cmd
from rpa_recorder.models import (
    ActionType,
    ClickPayload,
    InputPayload,
    RecordedAction,
    Recording,
)
from rpa_recorder.storage.db import create_engine, get_session, init_db
from rpa_recorder.storage.repositories import RecordingRepository

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.ext.asyncio import AsyncEngine


@pytest.fixture
def patched_engine(monkeypatch: pytest.MonkeyPatch) -> Iterator[AsyncEngine]:
    engine = create_engine("sqlite+aiosqlite:///:memory:")

    async def _setup() -> None:
        await init_db(engine)

    asyncio.run(_setup())
    monkeypatch.setattr(dependencies, "make_engine", lambda: engine)

    async def _noop_init() -> None:
        return None

    monkeypatch.setattr(dependencies, "init_database", _noop_init)
    yield engine

    async def _teardown() -> None:
        await engine.dispose()

    asyncio.run(_teardown())


class _StubPage:
    url = "https://example.com"

    async def goto(self, _url: str) -> None:
        return None


class _StubSession:
    def __init__(self, *_args: object, **_kwargs: object) -> None:
        self.page = _StubPage()

    async def __aenter__(self) -> _StubSession:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None


class _StubRecorder:
    """Yields a one-action recording so the heuristic + save path runs."""

    def __init__(self, _page: object, *, name: str, starting_url: str, **_kwargs: object) -> None:
        self._name = name
        self._url = starting_url
        self._id = uuid4()

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    def get_recording(self) -> Recording:
        return Recording(
            id=self._id,
            name=self._name,
            created_at=datetime(2026, 5, 4, 12, 0, tzinfo=UTC),
            starting_url=self._url,
            actions=[
                RecordedAction(
                    sequence=0,
                    timestamp=datetime(2026, 5, 4, 12, 0, tzinfo=UTC),
                    action_type=ActionType.INPUT,
                    payload=InputPayload(value="hi"),
                    url=self._url,
                ),
                RecordedAction(
                    sequence=1,
                    timestamp=datetime(2026, 5, 4, 12, 0, 1, tzinfo=UTC),
                    action_type=ActionType.CLICK,
                    payload=ClickPayload(),
                    url=self._url,
                ),
            ],
        )


def test_record_saves_recording_after_stop(
    patched_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Patch session + recorder + wait loop. Cmd must save and apply heuristic."""
    monkeypatch.setattr(record_cmd, "BrowserSession", _StubSession)
    monkeypatch.setattr(record_cmd, "Recorder", _StubRecorder)

    # Replace the indefinite wait with an immediate KeyboardInterrupt so the
    # finally block runs and the recording is saved.
    class _ImmediateInterrupt:
        async def wait(self) -> None:
            raise KeyboardInterrupt

    monkeypatch.setattr(asyncio, "Event", _ImmediateInterrupt)

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["record", "demo", "--url", "https://example.com"],
        catch_exceptions=False,
    )
    # Ctrl+C path returns 130
    assert result.exit_code == 130
    assert "Saved recording" in result.output

    # Verify the recording landed in the database with classified actions.
    async def _load_all() -> list[Recording]:
        out: list[Recording] = []
        async with get_session(patched_engine) as db:
            repo = RecordingRepository(db)
            summaries = await repo.list()
            for s in summaries:
                rec = await repo.get(s.id)
                if rec is not None:
                    out.append(rec)
        return out

    recordings = asyncio.run(_load_all())
    assert len(recordings) == 1
    rec = recordings[0]
    assert rec.name == "demo"
    assert len(rec.actions) >= 1  # heuristic may filter
    # Every saved action should have a non-default reasoning prefix.
    for action in rec.actions:
        assert action.classification_reasoning is not None
        assert action.classification_reasoning.startswith("[")


def test_record_classify_skipped_on_empty_recording(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Internal `_classify` is a no-op for empty recordings."""
    rec = Recording(
        id=uuid4(),
        name="empty",
        created_at=datetime(2026, 5, 4, 12, 0, tzinfo=UTC),
        starting_url="https://example.com",
        actions=[],
    )
    assert record_cmd._classify(rec) is rec


@pytest.mark.integration
def test_record_against_fixture_url() -> None:
    """Integration test placeholder.

    A real-browser test would invoke ``rpa record`` against a static fixture
    URL with ``--headless`` and Ctrl+C input, then assert the bronze JSONL
    exists and the recording was saved. Wired in M11.5 alongside the
    Playwright fixture infrastructure.
    """
    pytest.skip("real-browser integration coverage deferred to M11.5 fixture work")
