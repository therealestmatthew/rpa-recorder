"""Tests for `rpa list` and `rpa show` commands."""

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest
from typer.testing import CliRunner

from rpa_recorder.cli import dependencies
from rpa_recorder.cli.app import app
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


def _make_recording(name: str = "demo") -> Recording:
    return Recording(
        id=uuid4(),
        name=name,
        created_at=datetime(2026, 5, 4, 12, 0, tzinfo=UTC),
        starting_url="https://example.com",
        actions=[
            RecordedAction(
                sequence=0,
                timestamp=datetime(2026, 5, 4, 12, 0, tzinfo=UTC),
                action_type=ActionType.CLICK,
                payload=ClickPayload(),
                url="https://example.com",
            ),
            RecordedAction(
                sequence=1,
                timestamp=datetime(2026, 5, 4, 12, 0, 1, tzinfo=UTC),
                action_type=ActionType.INPUT,
                payload=InputPayload(value="secret", is_sensitive=True),
                url="https://example.com",
            ),
        ],
    )


@pytest.fixture
def patched_engine(monkeypatch: pytest.MonkeyPatch) -> Iterator[AsyncEngine]:
    """Create a fresh in-memory engine and patch CLI dependencies onto it."""
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


def _seed(engine: AsyncEngine, *recordings: Recording) -> None:
    async def _do() -> None:
        async with get_session(engine) as db:
            repo = RecordingRepository(db)
            for rec in recordings:
                await repo.save(rec)

    asyncio.run(_do())


def test_list_with_seeded_db(patched_engine: AsyncEngine) -> None:
    rec_a = _make_recording("login_flow")
    rec_b = _make_recording("checkout_flow")
    _seed(patched_engine, rec_a, rec_b)

    runner = CliRunner()
    result = runner.invoke(app, ["list"], catch_exceptions=False)
    assert result.exit_code == 0
    assert "login_flow" in result.output
    assert "checkout_flow" in result.output


def test_show_existing_recording(patched_engine: AsyncEngine) -> None:
    rec = _make_recording("login")
    _seed(patched_engine, rec)

    runner = CliRunner()
    result = runner.invoke(app, ["show", str(rec.id)], catch_exceptions=False)
    assert result.exit_code == 0
    assert "login" in result.output
    # is_sensitive=True payload must be redacted by default
    assert "secret" not in result.output
    assert "REDACTED" in result.output


def test_show_unknown_id_exits_nonzero(patched_engine: AsyncEngine) -> None:
    unknown = UUID("00000000-0000-0000-0000-000000000000")
    runner = CliRunner()
    result = runner.invoke(app, ["show", str(unknown)], catch_exceptions=False)
    assert result.exit_code == 1
    assert "Recording not found" in result.output


def test_show_invalid_uuid_exits_nonzero() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["show", "not-a-uuid"], catch_exceptions=False)
    assert result.exit_code == 1
    assert "invalid UUID" in result.output
