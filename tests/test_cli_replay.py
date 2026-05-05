"""Tests for `rpa replay`."""

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import pytest
from typer.testing import CliRunner

from rpa_recorder.cli import dependencies
from rpa_recorder.cli.app import app
from rpa_recorder.cli.commands import replay as replay_cmd
from rpa_recorder.models import (
    ActionType,
    ClickPayload,
    ElementSelector,
    ExecutionStatus,
    RecordedAction,
    Recording,
    RunResult,
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


class _FakeSession:
    """Stub that satisfies the BrowserSession surface used by `replay`."""

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        # Executor's __init__ uses page only via `.on(...)` for console + pageerror;
        # any object with a no-op `on` method works.
        self.page = _StubPage()

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None


class _StubPage:
    def on(self, *_args: object, **_kwargs: object) -> None:
        return None


def _make_recording() -> Recording:
    return Recording(
        id=uuid4(),
        name="demo",
        created_at=datetime(2026, 5, 4, 12, 0, tzinfo=UTC),
        starting_url="https://example.com",
        actions=[
            RecordedAction(
                sequence=0,
                timestamp=datetime(2026, 5, 4, 12, 0, tzinfo=UTC),
                action_type=ActionType.CLICK,
                payload=ClickPayload(),
                selector=ElementSelector(css="button"),
                url="https://example.com",
            ),
        ],
    )


def _seed(engine: AsyncEngine, rec: Recording) -> None:
    async def _do() -> None:
        async with get_session(engine) as db:
            await RecordingRepository(db).save(rec)

    asyncio.run(_do())


def _stub_run_result(rec_id: UUID) -> RunResult:
    started = datetime(2026, 5, 4, 12, 0, 0, tzinfo=UTC)
    ended = datetime(2026, 5, 4, 12, 0, 1, tzinfo=UTC)
    return RunResult(
        recording_id=rec_id,
        started_at=started,
        ended_at=ended,
        status=ExecutionStatus.SUCCESS,
        executions=[],
    )


def test_replay_with_monkeypatched_executor(
    patched_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rec = _make_recording()
    _seed(patched_engine, rec)

    captured_kwargs: dict[str, Any] = {}

    class _StubExecutor:
        def __init__(self, page: object, recording: Recording, **kwargs: Any) -> None:
            captured_kwargs["recording_id"] = recording.id
            captured_kwargs.update(kwargs)
            self._recording = recording

        async def run(self) -> RunResult:
            return _stub_run_result(self._recording.id)

    monkeypatch.setattr(replay_cmd, "Executor", _StubExecutor)
    monkeypatch.setattr(replay_cmd, "BrowserSession", _FakeSession)

    runner = CliRunner()
    result = runner.invoke(app, ["replay", str(rec.id)], catch_exceptions=False)
    assert result.exit_code == 0
    assert captured_kwargs["recording_id"] == rec.id


def test_replay_with_param_substitution(
    patched_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rec = _make_recording()
    _seed(patched_engine, rec)

    captured_kwargs: dict[str, Any] = {}

    class _StubExecutor:
        def __init__(self, page: object, recording: Recording, **kwargs: Any) -> None:
            captured_kwargs.update(kwargs)
            self._recording = recording

        async def run(self) -> RunResult:
            return _stub_run_result(self._recording.id)

    monkeypatch.setattr(replay_cmd, "Executor", _StubExecutor)
    monkeypatch.setattr(replay_cmd, "BrowserSession", _FakeSession)

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["replay", str(rec.id), "--param", "email=a@b.com", "--param", "lang=en"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    assert captured_kwargs["parameter_values"] == {"email": "a@b.com", "lang": "en"}


def test_replay_unknown_id_exits_nonzero(patched_engine: AsyncEngine) -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["replay", "00000000-0000-0000-0000-000000000000"],
        catch_exceptions=False,
    )
    assert result.exit_code == 1


def test_replay_invalid_uuid_exits_nonzero() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["replay", "not-a-uuid"], catch_exceptions=False)
    assert result.exit_code == 1


def test_replay_duplicate_param_exits_nonzero() -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["replay", str(uuid4()), "--param", "k=1", "--param", "k=2"],
        catch_exceptions=False,
    )
    assert result.exit_code != 0
