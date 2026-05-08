"""End-to-end tests for `rpa confirm <id>` (M11)."""

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
    RecordedAction,
    Recording,
    SemanticIntent,
)
from rpa_recorder.storage.db import create_engine, get_session, init_db
from rpa_recorder.storage.repositories import RecordingRepository

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncEngine


def _make_recording() -> Recording:
    return Recording(
        id=uuid4(),
        name="confirm-fixture",
        created_at=datetime(2026, 5, 6, tzinfo=UTC),
        starting_url="https://example.com",
        actions=[
            RecordedAction(
                sequence=0,
                timestamp=datetime(2026, 5, 6, tzinfo=UTC),
                action_type=ActionType.CLICK,
                payload=ClickPayload(),
                url="https://example.com",
                semantic_intent=SemanticIntent.UNKNOWN,
                classification_confidence=0.4,
            ),
            RecordedAction(
                sequence=1,
                timestamp=datetime(2026, 5, 6, tzinfo=UTC),
                action_type=ActionType.CLICK,
                payload=ClickPayload(),
                url="https://example.com",
                semantic_intent=SemanticIntent.SEARCH,
                classification_confidence=0.55,
            ),
            RecordedAction(
                sequence=2,
                timestamp=datetime(2026, 5, 6, tzinfo=UTC),
                action_type=ActionType.CLICK,
                payload=ClickPayload(),
                url="https://example.com",
                semantic_intent=SemanticIntent.SEARCH,
                classification_confidence=0.95,
            ),
        ],
    )


@pytest.fixture
def patched_engine(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[AsyncEngine]:
    """In-memory engine + temp bronze root for isolated CLI tests."""
    engine = create_engine("sqlite+aiosqlite:///:memory:")
    asyncio.run(init_db(engine))
    monkeypatch.setattr(dependencies, "make_engine", lambda: engine)

    async def _noop_init() -> None:
        return None

    monkeypatch.setattr(dependencies, "init_database", _noop_init)

    # Point bronze root somewhere temp so audit writes don't pollute the repo.
    cfg = dependencies._config()
    monkeypatch.setattr(cfg, "bronze_root", tmp_path / "bronze")

    yield engine

    asyncio.run(engine.dispose())


def _seed(engine: AsyncEngine, recording: Recording) -> None:
    async def _do() -> None:
        async with get_session(engine) as db:
            await RecordingRepository(db).save(recording)

    asyncio.run(_do())


def test_confirm_against_seeded_recording_accepts_relabels_skips(
    patched_engine: AsyncEngine,
) -> None:
    rec = _make_recording()
    _seed(patched_engine, rec)
    runner = CliRunner()
    # Below threshold (default 0.7) selects sequences 0 and 1.
    # Stdin: "a\n" accepts the first; "r\nlogin\n" relabels the second.
    result = runner.invoke(
        app,
        ["confirm", str(rec.id), "--no-audit-bronze"],
        input="a\nr\nlogin\n",
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    assert "accepted" in result.output
    assert "relabeled" in result.output

    async def _check() -> None:
        async with get_session(patched_engine) as db:
            reloaded = await RecordingRepository(db).get(rec.id)
            assert reloaded is not None
            by_seq = {a.sequence: a for a in reloaded.actions}
            assert by_seq[0].user_confirmed is True
            assert by_seq[1].user_confirmed is True
            assert by_seq[1].user_label == "login"

    asyncio.run(_check())


def test_confirm_with_by_intent_filter_surfaces_only_matching_intent(
    patched_engine: AsyncEngine,
) -> None:
    rec = _make_recording()
    _seed(patched_engine, rec)
    runner = CliRunner()
    # by_intent=search picks sequences 1 and 2.
    result = runner.invoke(
        app,
        [
            "confirm",
            str(rec.id),
            "--filter",
            "by_intent",
            "--intent",
            "search",
            "--no-audit-bronze",
        ],
        input="a\na\n",
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output

    async def _check() -> None:
        async with get_session(patched_engine) as db:
            reloaded = await RecordingRepository(db).get(rec.id)
            assert reloaded is not None
            by_seq = {a.sequence: a for a in reloaded.actions}
            assert by_seq[0].user_confirmed is False  # not surfaced
            assert by_seq[1].user_confirmed is True
            assert by_seq[2].user_confirmed is True

    asyncio.run(_check())


def test_confirm_unknown_recording_id_exits_nonzero(
    patched_engine: AsyncEngine,
) -> None:
    runner = CliRunner()
    bogus = UUID("00000000-0000-0000-0000-000000000000")
    result = runner.invoke(
        app,
        ["confirm", str(bogus)],
        catch_exceptions=False,
    )
    assert result.exit_code == 1
    assert "not found" in result.output


def test_confirm_invalid_uuid_exits_nonzero() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["confirm", "not-a-uuid"], catch_exceptions=False)
    assert result.exit_code == 1
    assert "invalid UUID" in result.output


def test_confirm_by_intent_without_intent_flag_errors(
    patched_engine: AsyncEngine,
) -> None:
    rec = _make_recording()
    _seed(patched_engine, rec)
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["confirm", str(rec.id), "--filter", "by_intent"],
        catch_exceptions=False,
    )
    assert result.exit_code == 1
    assert "intent" in result.output


def test_confirm_writes_bronze_audit_when_enabled(
    patched_engine: AsyncEngine,
    tmp_path: Path,
) -> None:
    rec = _make_recording()
    _seed(patched_engine, rec)
    runner = CliRunner()
    # Default --audit-bronze is on; below_threshold picks 2 actions.
    result = runner.invoke(
        app,
        ["confirm", str(rec.id)],
        input="a\na\n",
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output

    audit_path = tmp_path / "bronze" / "reviews" / str(rec.id) / "decisions.jsonl"
    assert audit_path.exists()
    contents = audit_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(contents) == 2
    assert "accept" in contents[0]
