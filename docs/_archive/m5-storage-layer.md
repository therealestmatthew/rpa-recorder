# M5 — Storage layer

**Status:** completed

**Commit:** `7299cb9 feat(storage): add async SQLAlchemy schema, repositories, and config`

**Source:** `.claude/plans/bootstrap.md` (Storage Specification, Configuration) and the persisted shape laid out in `.claude/plans/data-capture.md §2/§4/§5`.

## Goal

Persist a `Recording` aggregate (recording + actions + network log) and a `RunResult` aggregate (run + executions + attempts) to async SQLAlchemy 2.0 + aiosqlite, plus a `Config` loader for env vars and `.env` files. Repositories adapt Pydantic models to ORM rows and back.

## What shipped

### `src/rpa_recorder/storage/db.py`

Seven tables, all subclasses of a single `Base(DeclarativeBase)`. UUID primary keys are `String(36)` for SQLite portability. JSON columns hold nested Pydantic structures.

| Table | Notable columns |
|---|---|
| `recordings` | id, name, description, created_at, created_by, starting_url, JSON `parameters`, JSON `tags`. Cascading relationships to `actions` and `network_events`. |
| `recorded_actions` | recording_id (FK CASCADE), sequence, timestamp, action_type, url, page_title, frame_url, semantic_intent, classification_confidence, classification_reasoning, user_confirmed, user_label, is_parameterized, parameter_name; JSON `payload`, `selector`, `element_context`, `viewport`. |
| `network_events` | autoincrement id, recording_id (FK CASCADE), timestamp, method, url, status, JSON `request_headers`, response_summary. |
| `run_results` | id, recording_id (FK CASCADE), started_at, ended_at, status, summary, JSON `parameter_values`. Cascading relationship to `executions`. |
| `action_executions` | run_id (FK CASCADE), action_id (logical reference, no FK so run history survives recording mutations), status, duration_ms, JSON `recovery`. Cascading relationship to `attempts`. |
| `execution_attempts` | action_execution_id (FK CASCADE), attempt_number, started_at, ended_at, status, failure_mode, error_message, screenshot_path, dom_snapshot_path, accessibility_snapshot_path, JSON `selector_used`, JSON `console_log`, JSON `js_errors`. |
| `llm_calls` | called_for, model, Text `prompt`, Text `response`, optional FKs (recording_id, run_id, action_id), input_tokens, output_tokens, latency_ms, created_at, error. Independent (no relationship). |

Engine + session helpers:

```python
def create_engine(database_url: str, *, echo: bool = False) -> AsyncEngine: ...
async def init_db(engine: AsyncEngine) -> None: ...

@asynccontextmanager
async def get_session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Yield a session that auto-commits on success, rolls back on exception."""
```

`async_sessionmaker(engine, expire_on_commit=False)` so loaded objects remain usable post-commit.

### `src/rpa_recorder/storage/repositories.py`

Repositories DO NOT commit on their own — `get_session()` owns the transaction boundary so callers can compose multiple ops in one unit of work. They `flush()` to surface insert errors early.

- `RecordingRepository(session)` — `save`, `get`, `list`, `delete`. Loading uses `selectinload` for `actions` and `network_events`. Action payloads are reconstructed by dispatching on `action_type` to the right Pydantic class (`ClickPayload`/`InputPayload`/`NavigatePayload`/`SelectPayload`/dict fallback for `KEY_PRESS` etc.).
- `RunResultRepository(session)` — `save`, `get`, `list_for_recording`. Loading uses chained `selectinload` for `executions → attempts`.
- `RecordingSummary` and `RunResultSummary` Pydantic projections used by list endpoints (M8 / M12).

Round-tripping the redaction context: stored values are raw (we need them for replay), and redaction is applied via `model_dump(context={"redact_secrets": True})` at output boundaries — see `tests/test_storage.py::test_recording_round_trips` which asserts the context still applies after a save → load cycle.

### `src/rpa_recorder/config.py`

`Config(BaseSettings)` with `RPA_`-prefixed env-var loading and `.env` support:

- `database_url: str = "sqlite+aiosqlite:///rpa.db"`
- `anthropic_api_key: SecretStr | None = None`
- `classifier_confidence_threshold: float = 0.7`
- `screenshots_dir: Path = Path("screenshots")`
- `traces_dir: Path = Path("traces")`
- `recordings_dir: Path = Path("recordings")`
- `dom_dir: Path = Path("dom")`
- `storage_state_dir: Path = Path("storage_state")`
- `default_browser: Literal["chromium"] = "chromium"`
- `default_headless: bool = False`

### Toolchain knobs

`pyproject.toml` was updated to add `pydantic_settings.BaseSettings` and `sqlalchemy.orm.DeclarativeBase` to `[tool.ruff.lint.flake8-type-checking].runtime-evaluated-base-classes`, so subclasses can use annotation-only imports (e.g., `Mapped[datetime]`) without ruff demanding TYPE_CHECKING gating that SQLAlchemy can't tolerate at class-construction time.

## Tests

`tests/test_storage.py` — 7 tests:

1. `test_init_db_creates_all_tables` — assert all 7 tables via `inspect(engine).get_table_names()`.
2. `test_recording_round_trips` — save a Recording with a CLICK + a sensitive INPUT action, load via a fresh session, deep-equal on the model fields. Verify redaction context still applies after the round trip.
3. `test_list_recordings_returns_summaries` — three saves, list returns summaries with `action_count == 2` for each.
4. `test_delete_recording_cascades` — actions and network events are removed via cascade.
5. `test_run_result_round_trips` — RunResult with one ActionExecution + one ExecutionAttempt persists; `list_for_recording` returns a single `RunResultSummary`.
6. `test_config_defaults` — defaults match the field declarations.
7. `test_config_reads_env` — `RPA_DATABASE_URL` and `RPA_CLASSIFIER_CONFIDENCE_THRESHOLD` env vars override.

Tests use a tmp-file SQLite via the `_engine_for(tmp_path)` async context-manager helper; `engine.dispose()` runs in `finally`.

## Critical files

- `src/rpa_recorder/storage/db.py`
- `src/rpa_recorder/storage/repositories.py`
- `src/rpa_recorder/config.py`
- `pyproject.toml` (ruff `runtime-evaluated-base-classes`)
- `tests/test_storage.py`
