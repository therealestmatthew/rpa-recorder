# storage

Async SQLAlchemy 2.0 silver-tier storage (M5). aiosqlite by default;
asyncpg available via the `postgres` extra. Per-operation `AsyncSession`
context managers; one shared `AsyncEngine` per process.

## Layout

```
storage/
├── __init__.py
├── db.py            # init_db(), get_engine(), get_session() context manager
└── repositories.py  # one Repository class per silver table
```

## Silver tables

Seven tables plus the bronze pointer index:

| Table | Owner milestone | Purpose |
|---|---|---|
| `recordings` | M2 / M5 | One row per recording; URL, started_at, storage_state path |
| `recorded_actions` | M2 / M5 | Per-event row; element selector, value, intent, confidence |
| `network_events` | M5 | Request/response metadata; bodies live in `data/bronze/<id>/network.har` |
| `run_results` | M5 | One row per replay run |
| `action_executions` | M5 | One row per attempted action within a run |
| `execution_attempts` | M5 | Per-attempt detail (M10 recovery writes here) |
| `llm_calls` | M9 | Prompt/response audit row; full payload in `data/bronze/llm/...` |
| `bronze_artifacts` | M6.5 | Pointers to bronze blobs (path, type, size, sha256) |

## Conventions

- **One `AsyncEngine` per process.** Created at app startup
  (`init_db()`), shared across coroutines via the engine's pool.
- **Sessions are per-operation.** Acquired via `get_session()` context
  manager and never reused across operations. Stale sessions are a
  source of silent transaction leaks.
- **SQLite WAL mode is enabled.** `init_db()` runs
  `PRAGMA journal_mode=WAL` and `PRAGMA busy_timeout=5000` so concurrent
  readers don't block writers. Above ~2 concurrent writers
  (i.e., a real worker fleet), prefer Postgres.
- **Postgres is opt-in.** Install the `postgres` extra
  (`uv sync --extra postgres`) and set `RPA_DATABASE_URL` to a
  `postgresql+asyncpg://...` URL. Schema is identical.
- **Repositories own SQL; routers and CLI handlers do not.** Add a
  method to the relevant `*Repository` class instead of inlining queries
  in callers.

## Adding a silver table

1. Define the SQLAlchemy `DeclarativeBase` subclass in `db.py`.
2. Add a Pydantic model in [`models/`](../models/) for the in-memory
   shape.
3. Add a `<Name>Repository` class in `repositories.py` with at least
   `create`, `get`, `list`, `update` methods as needed.
4. If the new table feeds gold, add a promotion fn in
   [`medallion/`](../medallion/) and wire it into the
   `promote_silver_to_gold` job in [`workers/`](../workers/).
5. Add tests in `tests/test_storage_<name>.py`.

## See also

- [`docs/_archive/m5-storage-layer.md`](../../../docs/_archive/m5-storage-layer.md) — milestone doc.
- [`models/README.md`](../models/README.md) — Pydantic shapes that mirror these tables.
- [`medallion/README.md`](../medallion/README.md) — bronze ↔ silver ↔ gold flow.
