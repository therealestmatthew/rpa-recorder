# `rpa_recorder.integration`

Library-mode entry point for external recorders. Use this when a non-Playwright
host (Selenium + Python + JS injection, an Electron driver, a custom WebDriver
wrapper) wants to layer rpa-recorder's bronze capture and heuristic classifier
on top of its own event source.

## What it gives you

| Component | Purpose |
|-----------|---------|
| [`SeleniumEvent`](events.py) | Pydantic input shape your host emits per captured event |
| [`SeleniumEventTranslator`](translator.py) | Stateless `SeleniumEvent` → `RecordedAction` |
| [`IngestSession`](session.py) | Async lifecycle facade (recording id, bronze, classifier, DB) |
| [`SyncIngestSession`](session.py) | Sync wrapper over `IngestSession` for synchronous hosts |

## What it does NOT do

- It does not import `selenium`. The package stays driver-agnostic.
- It does not inject JavaScript. Your host already does its own injection.
- It does not replay or recover. Replay is Playwright-coupled and out of scope here.
- It does not call the LLM classifier. Heuristic only.

## Quick start (sync host)

```python
from rpa_recorder import (
    SyncIngestSession, SeleniumEvent, SeleniumLocators, SeleniumTarget,
)

with SyncIngestSession.create(
    name="login flow",
    starting_url="https://example.com/login",
) as session:
    session.ingest_event(SeleniumEvent(
        event_type="input",
        timestamp_ms=1_730_000_000_000,
        url="https://example.com/login",
        locators=SeleniumLocators(id="username", name="username"),
        target=SeleniumTarget(tag="input", input_type="text"),
        payload={"value": "alice"},
    ))
    session.ingest_event(SeleniumEvent(
        event_type="input",
        timestamp_ms=1_730_000_000_500,
        url="https://example.com/login",
        locators=SeleniumLocators(id="password", name="password"),
        target=SeleniumTarget(tag="input", input_type="password"),
        payload={"value": "secret"},  # auto-flagged is_sensitive
    ))
    session.ingest_event(SeleniumEvent(
        event_type="click",
        timestamp_ms=1_730_000_001_000,
        url="https://example.com/login",
        locators=SeleniumLocators(css="button[type='submit']"),
        target=SeleniumTarget(tag="button"),
    ))
    # __exit__ runs finalize() → classifier → SQL persist + bronze finalize
```

## Quick start (async host)

```python
from rpa_recorder import IngestSession, SeleniumEvent

async with await IngestSession.create(
    name="login flow",
    starting_url="https://example.com/login",
) as session:
    await session.ingest_event(SeleniumEvent(...))
    # __aexit__ runs finalize() on clean exit
```

## Storage

Both sessions share the standard `RPA_BRONZE_ROOT` and `RPA_DATABASE_URL`
configuration ([`rpa_recorder.config.Config`](../config.py)). Recordings ingested
this way land in the same bronze tier and SQL DB as Playwright recordings,
tagged on `RecordingRow.source` (default `"selenium"` for this module).

To filter:

```sql
SELECT * FROM recordings WHERE source = 'selenium';
```

To override storage paths per-host:

```bash
RPA_BRONZE_ROOT=/var/lib/rpa/bronze RPA_DATABASE_URL=sqlite+aiosqlite:////var/lib/rpa/rpa.db python your_host.py
```

## Mapping reference (Selenium → ElementSelector)

| Host-provided locator | Maps to `ElementSelector` field |
|-----------------------|----------------------------------|
| `By.ID="foo"`         | `css="#foo"` (when no explicit `css` given) |
| `By.CSS_SELECTOR=...` | `css=...` (passed through) |
| `By.XPATH=...`        | `xpath=...` (passed through) |
| `By.NAME=...`         | `css='[name="..."]'` (when no `css`/`id`) |
| `By.LINK_TEXT=...`    | `text_content=...` |
| `By.PARTIAL_LINK_TEXT=...` | `text_content=...` |
| `By.CLASS_NAME=...`   | `css=".classname"` (last resort) |
| `By.TAG_NAME=...`     | `css="tag"` (last resort) |
| `data-testid` (host detects via JS) | `test_id=...` |
| `aria-label` (host detects via JS) | `accessible_name=...` |
| `role` attribute      | `role=...` |

The translator packs every available strategy into one `ElementSelector` so
replay has multiple fallbacks. For best results, host-side JS should derive
`aria-label`, `role`, and `data-testid` and pass them in `SeleniumLocators`.

## Sensitive input

If `target.input_type == "password"`, the translator marks the action's
`InputPayload.is_sensitive = True`, which triggers value redaction in
`RecordedAction.model_dump(context={"redact_secrets": True})`. Hosts can
also set `payload["is_sensitive"] = True` explicitly to override.

## Migration note

Adding the `source` column to `recordings` is additive but does NOT
auto-migrate existing on-disk SQLite databases. For dev installs it is
simplest to delete `rpa.db` and let `init_db()` recreate the schema. For
shared databases, run once:

```sql
ALTER TABLE recordings ADD COLUMN source VARCHAR(32) DEFAULT 'playwright' NOT NULL;
```
