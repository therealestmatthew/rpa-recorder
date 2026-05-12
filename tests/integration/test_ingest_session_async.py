"""End-to-end tests for `IngestSession` (async lifecycle facade).

Each test creates an isolated `Config` pointing at `tmp_path`, drives a few
events through the session, finalizes, and asserts both bronze (JSONL on disk
+ pointer rows in SQL) and the SQL `Recording`/`RecordedAction` rows.
"""

import json
from pathlib import Path

import pytest

from rpa_recorder.config import Config
from rpa_recorder.integration import (
    IngestSession,
    SeleniumEvent,
    SeleniumLocators,
    SeleniumTarget,
)
from rpa_recorder.medallion import paths as bronze_paths
from rpa_recorder.medallion.bronze_store import LocalFilesystemStore
from rpa_recorder.models import ActionType, SemanticIntent
from rpa_recorder.storage.db import create_engine, get_session
from rpa_recorder.storage.repositories import (
    BronzeArtifactRepository,
    RecordingRepository,
)

# Suppress aiosqlite's connection-deallocator ResourceWarning. See test_bronze_writes.py.
pytestmark = pytest.mark.filterwarnings(
    "ignore::pytest.PytestUnraisableExceptionWarning",
)


def _config_for(tmp_path: Path) -> Config:
    db = tmp_path / "rpa.db"
    return Config(
        database_url=f"sqlite+aiosqlite:///{db}",
        bronze_root=tmp_path / "bronze",
    )


def _login_event_sequence(base_url: str) -> list[SeleniumEvent]:
    """A minimal login-flow capture that the heuristic classifier should label."""
    return [
        SeleniumEvent(
            event_type="input",
            timestamp_ms=1_730_000_000_000,
            url=base_url,
            locators=SeleniumLocators(id="username", name="username"),
            target=SeleniumTarget(tag="input", input_type="text"),
            payload={"value": "alice"},
        ),
        SeleniumEvent(
            event_type="input",
            timestamp_ms=1_730_000_000_500,
            url=base_url,
            locators=SeleniumLocators(id="password", name="password"),
            target=SeleniumTarget(tag="input", input_type="password"),
            payload={"value": "hunter2"},
        ),
        SeleniumEvent(
            event_type="click",
            timestamp_ms=1_730_000_001_000,
            url=base_url,
            locators=SeleniumLocators(css="button[type='submit']"),
            target=SeleniumTarget(
                tag="button",
                attributes={"type": "submit"},
                visible_text="Sign in",
                parent_form_id="login-form",
            ),
        ),
    ]


class TestIngestSessionRoundTrip:
    async def test_finalize_writes_jsonl_and_sql_with_source(self, tmp_path: Path) -> None:
        cfg = _config_for(tmp_path)
        async with await IngestSession.create(
            name="login",
            starting_url="https://example.com/login",
            config=cfg,
        ) as session:
            for ev in _login_event_sequence("https://example.com/login"):
                await session.ingest_event(ev)
            rec_id = session.recording_id

        # JSONL on disk has 3 events.
        store = LocalFilesystemStore(cfg.bronze_root)
        content = await store.get(bronze_paths.recording_events_jsonl(rec_id))
        lines = [line for line in content.decode("utf-8").split("\n") if line]
        assert len(lines) == 3
        # Each line is valid JSON with the expected event type.
        types = [json.loads(line)["action_type"] for line in lines]
        assert types == ["input", "input", "click"]

        # SQL has the recording with source="selenium" and 3 actions.
        engine = create_engine(cfg.database_url)
        try:
            async with get_session(engine) as sql:
                repo = RecordingRepository(sql)
                rec = await repo.get(rec_id)
            assert rec is not None
            assert rec.source == "selenium"
            assert len(rec.actions) == 3
        finally:
            await engine.dispose()

    async def test_password_input_marked_sensitive(self, tmp_path: Path) -> None:
        cfg = _config_for(tmp_path)
        async with await IngestSession.create(
            name="login",
            starting_url="https://example.com/login",
            config=cfg,
        ) as session:
            for ev in _login_event_sequence("https://example.com/login"):
                await session.ingest_event(ev)

        # Round-trip from JSONL: password input is_sensitive=True.
        store = LocalFilesystemStore(cfg.bronze_root)
        content = await store.get(bronze_paths.recording_events_jsonl(session.recording_id))
        lines = [json.loads(line) for line in content.decode("utf-8").split("\n") if line]
        password_line = lines[1]
        assert password_line["payload"]["is_sensitive"] is True

    async def test_classifier_assigns_login_intent(self, tmp_path: Path) -> None:
        from rpa_recorder.models import InputPayload

        cfg = _config_for(tmp_path)
        async with await IngestSession.create(
            name="login",
            starting_url="https://example.com/login",
            config=cfg,
        ) as session:
            for ev in _login_event_sequence("https://example.com/login"):
                await session.ingest_event(ev)
            rec_id = session.recording_id

        engine = create_engine(cfg.database_url)
        try:
            async with get_session(engine) as sql:
                rec = await RecordingRepository(sql).get(rec_id)
            assert rec is not None
            # Find the password input by `is_sensitive`; LoginClassifier should
            # fire (0.95 confidence) and shadow the catch-all form_fill rule.
            password_action = next(
                a
                for a in rec.actions
                if a.action_type == ActionType.INPUT
                and isinstance(a.payload, InputPayload)
                and a.payload.is_sensitive
            )
            assert password_action.semantic_intent == SemanticIntent.LOGIN
            assert password_action.classification_confidence >= 0.9
        finally:
            await engine.dispose()

    async def test_run_classifier_false_leaves_intent_unknown(self, tmp_path: Path) -> None:
        cfg = _config_for(tmp_path)
        async with await IngestSession.create(
            name="login",
            starting_url="https://example.com/login",
            config=cfg,
            run_classifier=False,
        ) as session:
            for ev in _login_event_sequence("https://example.com/login"):
                await session.ingest_event(ev)
            rec_id = session.recording_id

        engine = create_engine(cfg.database_url)
        try:
            async with get_session(engine) as sql:
                rec = await RecordingRepository(sql).get(rec_id)
            assert rec is not None
            assert all(a.semantic_intent == SemanticIntent.UNKNOWN for a in rec.actions)
        finally:
            await engine.dispose()

    async def test_bronze_artifact_pointer_row_registered(self, tmp_path: Path) -> None:
        cfg = _config_for(tmp_path)
        async with await IngestSession.create(
            name="login",
            starting_url="https://example.com/login",
            config=cfg,
        ) as session:
            await session.ingest_event(_login_event_sequence("https://example.com/login")[0])
            rec_id = session.recording_id

        engine = create_engine(cfg.database_url)
        try:
            async with get_session(engine) as sql:
                rows = await BronzeArtifactRepository(sql).list_for_recording(rec_id)
            kinds = {r.kind for r in rows}
            assert "event_jsonl" in kinds
        finally:
            await engine.dispose()

    async def test_batch_ingest_assigns_monotonic_sequence(self, tmp_path: Path) -> None:
        cfg = _config_for(tmp_path)
        events = _login_event_sequence("https://example.com/login")
        async with await IngestSession.create(
            name="batch",
            starting_url="https://example.com/login",
            config=cfg,
        ) as session:
            actions = await session.ingest_events(events)
            assert [a.sequence for a in actions] == [0, 1, 2]

    async def test_caller_supplied_recording_id_is_honored(self, tmp_path: Path) -> None:
        from uuid import uuid4

        cfg = _config_for(tmp_path)
        rec_id = uuid4()
        async with await IngestSession.create(
            name="custom-id",
            starting_url="https://example.com/",
            config=cfg,
            recording_id=rec_id,
        ) as session:
            assert session.recording_id == rec_id

    async def test_custom_source_label_is_persisted(self, tmp_path: Path) -> None:
        cfg = _config_for(tmp_path)
        async with await IngestSession.create(
            name="puppeteer-host",
            starting_url="https://example.com/",
            config=cfg,
            source_label="puppeteer",
        ) as session:
            await session.ingest_event(
                SeleniumEvent(
                    event_type="click",
                    timestamp_ms=1,
                    url="https://example.com/",
                ),
            )
            rec_id = session.recording_id

        engine = create_engine(cfg.database_url)
        try:
            async with get_session(engine) as sql:
                rec = await RecordingRepository(sql).get(rec_id)
            assert rec is not None
            assert rec.source == "puppeteer"
        finally:
            await engine.dispose()


class TestIngestSessionLifecycle:
    async def test_double_finalize_raises(self, tmp_path: Path) -> None:
        cfg = _config_for(tmp_path)
        session = await IngestSession.create(
            name="double",
            starting_url="https://example.com/",
            config=cfg,
        )
        await session.ingest_event(
            SeleniumEvent(event_type="click", timestamp_ms=1, url="https://example.com/"),
        )
        await session.finalize()
        with pytest.raises(RuntimeError, match="already finalized"):
            await session.finalize()
        await session.aclose()

    async def test_aclose_is_idempotent(self, tmp_path: Path) -> None:
        cfg = _config_for(tmp_path)
        session = await IngestSession.create(
            name="idempotent",
            starting_url="https://example.com/",
            config=cfg,
        )
        await session.aclose()
        await session.aclose()  # should not raise
