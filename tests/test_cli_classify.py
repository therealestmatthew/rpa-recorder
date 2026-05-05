"""Tests for `rpa classify`."""

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from typer.testing import CliRunner

from rpa_recorder.cli import dependencies
from rpa_recorder.cli.app import app
from rpa_recorder.models import (
    ActionType,
    ElementContext,
    InputPayload,
    RecordedAction,
    Recording,
    SemanticIntent,
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


def _password_recording() -> Recording:
    """A recording whose only action is a typed-password input."""
    return Recording(
        id=uuid4(),
        name="login",
        created_at=datetime(2026, 5, 4, 12, 0, tzinfo=UTC),
        starting_url="https://example.com",
        actions=[
            RecordedAction(
                sequence=0,
                timestamp=datetime(2026, 5, 4, 12, 0, tzinfo=UTC),
                action_type=ActionType.INPUT,
                payload=InputPayload(value="hunter2", is_sensitive=True),
                element_context=ElementContext(
                    tag="input",
                    attributes={"type": "password"},
                ),
                url="https://example.com/login",
            ),
        ],
    )


def _seed(engine: AsyncEngine, rec: Recording) -> None:
    async def _do() -> None:
        async with get_session(engine) as db:
            await RecordingRepository(db).save(rec)

    asyncio.run(_do())


def _load(engine: AsyncEngine, rec_id: object) -> Recording | None:
    async def _do() -> Recording | None:
        async with get_session(engine) as db:
            return await RecordingRepository(db).get(rec_id)  # type: ignore[arg-type]

    return asyncio.run(_do())


def test_classify_updates_intent_fields(patched_engine: AsyncEngine) -> None:
    rec = _password_recording()
    _seed(patched_engine, rec)

    runner = CliRunner()
    result = runner.invoke(app, ["classify", str(rec.id)], catch_exceptions=False)
    assert result.exit_code == 0

    loaded = _load(patched_engine, rec.id)
    assert loaded is not None
    assert len(loaded.actions) == 1
    action = loaded.actions[0]
    assert action.semantic_intent is SemanticIntent.LOGIN
    assert action.classification_confidence == pytest.approx(0.95)
    assert action.classification_reasoning is not None
    assert action.classification_reasoning.startswith("[login]")


def test_classify_idempotent(patched_engine: AsyncEngine) -> None:
    rec = _password_recording()
    _seed(patched_engine, rec)

    runner = CliRunner()
    runner.invoke(app, ["classify", str(rec.id)], catch_exceptions=False)
    runner.invoke(app, ["classify", str(rec.id)], catch_exceptions=False)

    loaded = _load(patched_engine, rec.id)
    assert loaded is not None
    assert loaded.actions[0].semantic_intent is SemanticIntent.LOGIN
    assert loaded.actions[0].classification_confidence == pytest.approx(0.95)


def test_classify_unknown_id_exits_nonzero(patched_engine: AsyncEngine) -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["classify", "00000000-0000-0000-0000-000000000000"],
        catch_exceptions=False,
    )
    assert result.exit_code == 1
    assert "not found" in result.output.lower()


def test_classify_invalid_uuid_exits_nonzero() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["classify", "garbage"], catch_exceptions=False)
    assert result.exit_code == 1
    assert "invalid UUID" in result.output
