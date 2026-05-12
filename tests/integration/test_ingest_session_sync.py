"""Tests for `SyncIngestSession` — sync wrapper that drives the async core.

These tests are written as SYNC functions intentionally, so they exercise the
exact path a Selenium host would take. The wrapper internally runs an event
loop in a daemon thread.
"""

import json
from pathlib import Path

import pytest

from rpa_recorder.config import Config
from rpa_recorder.integration import (
    SeleniumEvent,
    SeleniumLocators,
    SeleniumTarget,
    SyncIngestSession,
)
from rpa_recorder.medallion import paths as bronze_paths

pytestmark = pytest.mark.filterwarnings(
    "ignore::pytest.PytestUnraisableExceptionWarning",
)


def _config_for(tmp_path: Path) -> Config:
    db = tmp_path / "rpa.db"
    return Config(
        database_url=f"sqlite+aiosqlite:///{db}",
        bronze_root=tmp_path / "bronze",
    )


def _three_events(url: str) -> list[SeleniumEvent]:
    return [
        SeleniumEvent(
            event_type="input",
            timestamp_ms=1_730_000_000_000,
            url=url,
            locators=SeleniumLocators(id="email"),
            target=SeleniumTarget(tag="input", input_type="email"),
            payload={"value": "alice@example.com"},
        ),
        SeleniumEvent(
            event_type="input",
            timestamp_ms=1_730_000_000_500,
            url=url,
            locators=SeleniumLocators(id="password"),
            target=SeleniumTarget(tag="input", input_type="password"),
            payload={"value": "secret"},
        ),
        SeleniumEvent(
            event_type="click",
            timestamp_ms=1_730_000_001_000,
            url=url,
            locators=SeleniumLocators(css="button[type='submit']"),
            target=SeleniumTarget(tag="button"),
        ),
    ]


class TestSyncIngestRoundTrip:
    def test_context_manager_finalizes_and_persists(self, tmp_path: Path) -> None:
        cfg = _config_for(tmp_path)
        events = _three_events("https://example.com/login")

        with SyncIngestSession.create(
            name="sync-login",
            starting_url="https://example.com/login",
            config=cfg,
        ) as session:
            rec_id = session.recording_id
            for ev in events:
                session.ingest_event(ev)

        # JSONL on disk has 3 lines.
        jsonl = cfg.bronze_root / Path(*bronze_paths.recording_events_jsonl(rec_id).split("/"))
        assert jsonl.exists()
        lines = [line for line in jsonl.read_text(encoding="utf-8").split("\n") if line]
        assert len(lines) == 3
        assert all("action_type" in json.loads(line) for line in lines)

    def test_explicit_finalize_returns_recording(self, tmp_path: Path) -> None:
        cfg = _config_for(tmp_path)
        session = SyncIngestSession.create(
            name="explicit",
            starting_url="https://example.com/login",
            config=cfg,
        )
        try:
            session.ingest_event(_three_events("https://example.com/login")[0])
            recording = session.finalize()
            assert recording.source == "selenium"
            assert recording.name == "explicit"
            assert len(recording.actions) == 1
        finally:
            session.close()

    def test_batch_ingest_assigns_sequence(self, tmp_path: Path) -> None:
        cfg = _config_for(tmp_path)
        with SyncIngestSession.create(
            name="batch",
            starting_url="https://example.com/login",
            config=cfg,
        ) as session:
            actions = session.ingest_events(_three_events("https://example.com/login"))
        assert [a.sequence for a in actions] == [0, 1, 2]

    def test_close_without_finalize_does_not_raise(self, tmp_path: Path) -> None:
        cfg = _config_for(tmp_path)
        session = SyncIngestSession.create(
            name="abort",
            starting_url="https://example.com/login",
            config=cfg,
        )
        session.ingest_event(_three_events("https://example.com/login")[0])
        session.close()
        # Closing again is idempotent.
        session.close()
