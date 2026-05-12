"""Standalone demo: drive `rpa_recorder.integration` from a synchronous host.

This script does NOT use Selenium — it simulates what a Selenium-based host
would do by handing pre-built `SeleniumEvent` objects to `SyncIngestSession`.
The point is to show the public API end-to-end: open a session, ingest events,
finalize, then verify the bronze JSONL and SQL `Recording`/action rows.

Run from the project root:

    uv run python examples/selenium_demo.py [--root /tmp/rpa-demo]

The --root flag chooses where the demo bronze tier and SQLite DB live; the
script defaults to a fresh subdirectory under the system temp dir so repeated
runs don't collide.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path

from rpa_recorder import (
    Config,
    SeleniumEvent,
    SeleniumLocators,
    SeleniumTarget,
    SyncIngestSession,
)
from rpa_recorder.medallion import paths as bronze_paths
from rpa_recorder.storage.db import create_engine, get_session
from rpa_recorder.storage.repositories import RecordingRepository


def _build_login_capture(base_url: str) -> list[SeleniumEvent]:
    return [
        SeleniumEvent(
            event_type="navigate",
            timestamp_ms=1_730_000_000_000,
            url=base_url,
            payload={"url": base_url},
        ),
        SeleniumEvent(
            event_type="input",
            timestamp_ms=1_730_000_000_500,
            url=base_url,
            locators=SeleniumLocators(id="username", name="username"),
            target=SeleniumTarget(tag="input", input_type="text"),
            payload={"value": "alice"},
        ),
        SeleniumEvent(
            event_type="input",
            timestamp_ms=1_730_000_001_000,
            url=base_url,
            locators=SeleniumLocators(id="password", name="password"),
            target=SeleniumTarget(tag="input", input_type="password"),
            payload={"value": "hunter2"},
        ),
        SeleniumEvent(
            event_type="click",
            timestamp_ms=1_730_000_001_500,
            url=base_url,
            locators=SeleniumLocators(
                css="button[type='submit']",
                aria_role="button",
                aria_label="Sign in",
            ),
            target=SeleniumTarget(
                tag="button",
                attributes={"type": "submit"},
                visible_text="Sign in",
                parent_form_id="login-form",
            ),
        ),
        SeleniumEvent(
            event_type="navigate",
            timestamp_ms=1_730_000_002_000,
            url=f"{base_url}/dashboard",
            payload={"url": f"{base_url}/dashboard"},
        ),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(tempfile.mkdtemp(prefix="rpa-demo-")),
        help="Storage root for bronze JSONL and SQLite DB",
    )
    args = parser.parse_args(argv)
    root: Path = args.root
    root.mkdir(parents=True, exist_ok=True)

    db_path = root / "rpa.db"
    bronze_root = root / "bronze"
    config = Config(
        database_url=f"sqlite+aiosqlite:///{db_path}",
        bronze_root=bronze_root,
    )

    base_url = "https://example.com/login"
    events = _build_login_capture(base_url)

    print(f"[demo] storage root: {root}")
    print(f"[demo] ingesting {len(events)} events")
    with SyncIngestSession.create(
        name="selenium-demo-login",
        starting_url=base_url,
        config=config,
    ) as session:
        rec_id = session.recording_id
        for event in events:
            session.ingest_event(event)

    jsonl_path = bronze_root / Path(*bronze_paths.recording_events_jsonl(rec_id).split("/"))
    print(f"[demo] bronze JSONL: {jsonl_path}")
    lines = [line for line in jsonl_path.read_text(encoding="utf-8").split("\n") if line]
    print(f"[demo] JSONL lines: {len(lines)}")
    intents = []
    for line in lines:
        envelope = json.loads(line)
        intents.append(envelope.get("semantic_intent", "unknown"))
    print(f"[demo] semantic_intents (pre-finalize, before classifier ran): {intents}")

    async def _read_back() -> None:
        engine = create_engine(config.database_url)
        try:
            async with get_session(engine) as sql:
                recording = await RecordingRepository(sql).get(rec_id)
            if recording is None:
                print("[demo] ERROR: recording not found in SQL")
                return
            print(f"[demo] SQL recording.source = {recording.source!r}")
            print(f"[demo] SQL action count: {len(recording.actions)}")
            for action in recording.actions:
                print(
                    f"[demo]   #{action.sequence}: {action.action_type.value:>10} "
                    f"intent={action.semantic_intent.value:<12} "
                    f"conf={action.classification_confidence:.2f}",
                )
        finally:
            await engine.dispose()

    asyncio.run(_read_back())
    print("[demo] done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
