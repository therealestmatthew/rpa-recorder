"""Tests for the SQLAlchemy schema, repositories, and config loader."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import inspect

from rpa_recorder.config import Config
from rpa_recorder.models import (
    ActionExecution,
    ActionType,
    ClickPayload,
    ElementSelector,
    ExecutionAttempt,
    ExecutionStatus,
    InputPayload,
    NetworkEvent,
    ParameterDef,
    RecordedAction,
    Recording,
    RunResult,
    SemanticIntent,
)
from rpa_recorder.storage.db import (
    create_engine,
    get_session,
    init_db,
)
from rpa_recorder.storage.repositories import (
    RecordingRepository,
    RunResultRepository,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    import pytest
    from sqlalchemy.ext.asyncio import AsyncEngine


@asynccontextmanager
async def _engine_for(tmp_path: Path) -> AsyncIterator[AsyncEngine]:
    db = tmp_path / "test.db"
    engine = create_engine(f"sqlite+aiosqlite:///{db}")
    try:
        await init_db(engine)
        yield engine
    finally:
        await engine.dispose()


def _sample_recording(name: str = "login flow") -> Recording:
    now = datetime.now(UTC)
    actions = [
        RecordedAction(
            sequence=1,
            timestamp=now,
            action_type=ActionType.CLICK,
            payload=ClickPayload(button="left"),
            selector=ElementSelector(
                test_id="submit-btn",
                role="button",
                accessible_name="Submit",
            ),
            url="https://example.com/login",
            page_title="Login",
        ),
        RecordedAction(
            sequence=2,
            timestamp=now,
            action_type=ActionType.INPUT,
            payload=InputPayload(value="hunter2", is_sensitive=True),
            selector=ElementSelector(css="#password"),
            url="https://example.com/login",
            semantic_intent=SemanticIntent.LOGIN,
            classification_confidence=0.95,
        ),
    ]
    network = [
        NetworkEvent(
            timestamp=now,
            method="POST",
            url="https://example.com/login",
            status=200,
            response_summary="200 OK",
        ),
    ]
    return Recording(
        name=name,
        description="round-trip fixture",
        created_at=now,
        starting_url="https://example.com/login",
        actions=actions,
        network_log=network,
        parameters={"username": ParameterDef(name="username", type="string")},
        tags=["test"],
    )


async def test_init_db_creates_all_tables(tmp_path: Path) -> None:
    async with _engine_for(tmp_path) as engine, engine.begin() as conn:
        tables = await conn.run_sync(lambda c: inspect(c).get_table_names())
    expected = {
        "recordings",
        "recorded_actions",
        "network_events",
        "run_results",
        "action_executions",
        "execution_attempts",
        "llm_calls",
    }
    assert expected.issubset(set(tables))


async def test_recording_round_trips(tmp_path: Path) -> None:
    rec = _sample_recording()
    async with _engine_for(tmp_path) as engine:
        async with get_session(engine) as session:
            await RecordingRepository(session).save(rec)
        async with get_session(engine) as session:
            loaded = await RecordingRepository(session).get(rec.id)

    assert loaded is not None
    assert loaded.id == rec.id
    assert loaded.name == rec.name
    assert loaded.starting_url == rec.starting_url
    assert "username" in loaded.parameters
    assert loaded.parameters["username"].type == "string"
    assert loaded.tags == ["test"]
    assert len(loaded.actions) == 2
    assert len(loaded.network_log) == 1

    a1, a2 = sorted(loaded.actions, key=lambda a: a.sequence)
    assert a1.action_type == ActionType.CLICK
    assert isinstance(a1.payload, ClickPayload)
    assert a1.payload.button == "left"
    assert a1.selector is not None and a1.selector.test_id == "submit-btn"

    assert a2.action_type == ActionType.INPUT
    assert isinstance(a2.payload, InputPayload)
    assert a2.payload.is_sensitive is True
    assert a2.payload.value == "hunter2"
    assert a2.semantic_intent == SemanticIntent.LOGIN

    # Redaction context still applies after a round-trip.
    redacted = a2.model_dump(context={"redact_secrets": True})
    assert redacted["payload"]["value"] == "***REDACTED***"


async def test_list_recordings_returns_summaries(tmp_path: Path) -> None:
    async with _engine_for(tmp_path) as engine:
        async with get_session(engine) as session:
            repo = RecordingRepository(session)
            for i in range(3):
                await repo.save(_sample_recording(name=f"rec-{i}"))
        async with get_session(engine) as session:
            summaries = await RecordingRepository(session).list()

    assert len(summaries) == 3
    assert {s.name for s in summaries} == {"rec-0", "rec-1", "rec-2"}
    assert all(s.action_count == 2 for s in summaries)


async def test_delete_recording_cascades(tmp_path: Path) -> None:
    rec = _sample_recording()
    async with _engine_for(tmp_path) as engine:
        async with get_session(engine) as session:
            await RecordingRepository(session).save(rec)
        async with get_session(engine) as session:
            assert await RecordingRepository(session).delete(rec.id) is True
        async with get_session(engine) as session:
            assert await RecordingRepository(session).get(rec.id) is None


async def test_run_result_round_trips(tmp_path: Path) -> None:
    rec = _sample_recording()
    now = datetime.now(UTC)
    run = RunResult(
        recording_id=rec.id,
        started_at=now,
        ended_at=now,
        status=ExecutionStatus.SUCCESS,
        parameter_values={"username": "alice"},
        executions=[
            ActionExecution(
                action_id=rec.actions[0].id,
                status=ExecutionStatus.SUCCESS,
                duration_ms=120,
                attempts=[
                    ExecutionAttempt(
                        attempt_number=1,
                        started_at=now,
                        ended_at=now,
                        status=ExecutionStatus.SUCCESS,
                        selector_used=rec.actions[0].selector,
                    ),
                ],
            ),
        ],
        summary="all green",
    )

    async with _engine_for(tmp_path) as engine:
        async with get_session(engine) as session:
            await RecordingRepository(session).save(rec)
            await RunResultRepository(session).save(run)
        async with get_session(engine) as session:
            loaded = await RunResultRepository(session).get(run.id)
            summaries = await RunResultRepository(session).list_for_recording(rec.id)

    assert loaded is not None
    assert loaded.status == ExecutionStatus.SUCCESS
    assert loaded.parameter_values == {"username": "alice"}
    assert len(loaded.executions) == 1
    assert loaded.executions[0].duration_ms == 120
    assert len(loaded.executions[0].attempts) == 1
    assert loaded.executions[0].attempts[0].selector_used is not None
    assert loaded.executions[0].attempts[0].selector_used.test_id == "submit-btn"

    assert len(summaries) == 1
    assert summaries[0].recording_id == rec.id


def test_config_defaults() -> None:
    cfg = Config()
    assert cfg.database_url.startswith("sqlite+aiosqlite")
    assert cfg.classifier_confidence_threshold == 0.7
    assert cfg.default_browser == "chromium"
    assert cfg.recordings_dir == Path("recordings")
    assert cfg.dom_dir == Path("dom")


def test_config_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RPA_DATABASE_URL", "sqlite+aiosqlite:///custom.db")
    monkeypatch.setenv("RPA_CLASSIFIER_CONFIDENCE_THRESHOLD", "0.9")
    cfg = Config()
    assert cfg.database_url == "sqlite+aiosqlite:///custom.db"
    assert cfg.classifier_confidence_threshold == 0.9
