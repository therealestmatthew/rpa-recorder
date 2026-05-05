# Medallion Architecture + Worker Setup for `rpa_recorder`

> **Status:** Ready for execution. Decisions confirmed via Q&A — see *Decisions log* at end.

## Context

The bootstrap spec ([.claude/plans/bootstrap.md](.claude/plans/bootstrap.md)) defines `rpa_recorder` as a four-layer system: **record → classify → replay → recover**. After 5 commits the recorder produces a heterogeneous mix of artifacts:

- structured event envelopes from page-side JS (forwarded via `__rpa_capture`)
- HAR network logs and Playwright trace `.zip` files
- per-failure screenshots, DOM dumps, and accessibility snapshots
- LLM call logs (prompt/response/tokens/latency) once the classifier and recovery layers ship

These land in 7 normalized SQL tables plus loose files under `screenshots/`, `traces/`, `dom/`, `recordings/`, `storage_state/`. The spec says nothing about how to *organize* this growing artifact set for replay analytics, classifier feedback loops, cost dashboards, or training-data exports — and nothing about running multiple recordings/replays concurrently.

**Two extensions:**

1. **Medallion (bronze / silver / gold) layout** to separate raw capture from validated rows from analytics-ready aggregates, so questions like *"what's our classifier accuracy this week?"* and *"replay this recording with healed selectors"* have a clear data home.
2. **ARQ + Redis worker queue** so replay runs, LLM-heavy classifications, and medallion promotions execute out of the FastAPI request path, and so multiple replays run in parallel.

Both extensions are **purely additive** to the bootstrap spec — no changes to existing schemas, models, or contracts.

---

## Scope

**In scope**
- Medallion directory + table layout (bronze on disk, silver in SQL, gold split between hot SQLite and cold DuckDB/Parquet)
- `BronzeStore` storage abstraction (filesystem v1, cloud-ready)
- Page-side JS reorganized into a typed subdirectory package with `recorder/`, `replay/`, `shared/` splits and full stub set
- ARQ + Redis workers for replay, classification, summary, medallion promotion, bronze compaction, pruning
- FastAPI integration (job enqueue + WebSocket pub/sub)
- File-level change list, dependency additions, milestone placement (Option A: interleaved into M5.5 and M11.5)

**Out of scope (explicit)**
- Cloud object storage backends (S3/MinIO) — the abstraction is in place; only `LocalFilesystemStore` ships in v1
- Distributed multi-machine workers — single-host Redis is enough for portfolio scope
- BI tooling (Superset, Metabase) on top of gold — schema makes it possible, deployment is later
- Replacing the Anthropic SDK or any other existing dependency
- Backfilling existing recordings (none exist yet)

---

## Architecture overview

```
┌───────────────────────────────┐         ┌─────────────────────┐
│ Browser (Playwright + JS)     │         │ FastAPI control     │
│  page_scripts/recorder/*.js   │         │ plane (HTTP + WS)   │
└──────────────┬────────────────┘         └──────┬──────────────┘
               │ envelopes via                    │ enqueue_job
               │ __rpa_capture                    │ subscribe(run:*)
               ▼                                  ▼
┌─────────────────────────────────────────────────────────────────┐
│ BRONZE  (immutable, append-only, schema-on-read)                │
│  Storage: BronzeStore protocol  →  LocalFilesystemStore (v1)    │
│   data/bronze/recordings/<id>/raw_events.jsonl   (hot)          │
│   data/bronze/recordings/<id>/raw_events.parquet (cold, post-   │
│                                                   compaction)   │
│   data/bronze/recordings/<id>/network.har                       │
│   data/bronze/recordings/<id>/trace.zip                         │
│   data/bronze/runs/<id>/attempts/<n>/{screenshot,dom,a11y}.*    │
│   data/bronze/llm/<call-id>.json                                │
│  Index: bronze_artifacts table (path + sha256 + size + FKs)     │
└────────────────────┬────────────────────────────────────────────┘
                     │ promote_bronze_to_silver
                     │ (validates each envelope via Pydantic)
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│ SILVER  (validated, normalized, queryable — existing 7 tables)  │
│  recordings, recorded_actions, network_events, run_results,     │
│  action_executions, execution_attempts, llm_calls               │
└────────────────────┬────────────────────────────────────────────┘
                     │ promote_silver_to_gold
                     │ (idempotent; hourly cron + on-demand)
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│ GOLD                                                            │
│  HOT  (SQLite, low-latency reads from FastAPI/CLI):             │
│    gold_recording_metrics, gold_run_dashboard                   │
│  COLD (DuckDB-on-Parquet, analytics-grade):                     │
│    gold_classifier_accuracy_history.parquet                     │
│    gold_llm_costs_daily.parquet                                 │
│    gold_training_data.parquet                                   │
│    gold_replay_scripts/<recording-id>/<version>.parquet         │
└─────────────────────────────────────────────────────────────────┘

ARQ workers process jobs from Redis, stream live progress via Redis
pub/sub on `run:{run_id}` channels; FastAPI WebSocket bridges to the
HTTP client. Cron jobs handle gold recomputation, bronze compaction,
and retention pruning.
```

---

## Part 1: Medallion data layout

### 1.1 Bronze — raw, immutable, append-only

#### Storage abstraction

A `BronzeStore` Protocol decouples write/read sites from any specific backend. v1 ships a `LocalFilesystemStore`; an `S3Store` / `MinIOStore` can drop in later without touching recorder, executor, or workers.

```python
# src/rpa_recorder/medallion/bronze_store.py
from typing import Protocol, BinaryIO

class BronzeStore(Protocol):
    async def put(self, path: str, data: bytes | BinaryIO) -> str: ...   # returns sha256
    async def append_line(self, path: str, line: str) -> None: ...        # JSONL append
    async def get(self, path: str) -> bytes: ...
    async def list(self, prefix: str) -> list[str]: ...
    async def delete(self, path: str) -> None: ...
    async def stat(self, path: str) -> tuple[int, str]: ...               # (size, sha256)

class LocalFilesystemStore:
    def __init__(self, root: Path) -> None: ...
    # ...implementation against pathlib.Path under root...
```

The store is wired in `config.py` from `RPA_BRONZE_ROOT` (default `./data/bronze/`) and passed to writers via DI.

#### On-disk layout (root = `./data/bronze/` by default)

```
data/bronze/
├── recordings/
│   └── <recording-id>/
│       ├── raw_events.jsonl     # hot append-line on every capture
│       ├── raw_events.parquet   # written by compact_bronze_to_parquet (cron)
│       ├── network.har          # Playwright HAR on session close
│       └── trace.zip            # Playwright trace bundle
├── runs/
│   └── <run-id>/
│       └── attempts/<n>/
│           ├── screenshot.png
│           ├── dom.html
│           └── a11y.json
└── llm/
    └── <call-id>.json           # full Anthropic request + response
```

#### DB pointer index

```python
class BronzeArtifactRow(Base):
    __tablename__ = "bronze_artifacts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kind: Mapped[str]           # event_jsonl | event_parquet | har | trace
                                # | screenshot | dom | a11y | llm_call
    path: Mapped[str]           # store-relative path (backend-agnostic)
    sha256: Mapped[str]
    size_bytes: Mapped[int]
    created_at: Mapped[datetime]
    recording_id: Mapped[str | None] = mapped_column(ForeignKey("recordings.id"))
    run_id: Mapped[str | None]   = mapped_column(ForeignKey("run_results.id"))
    attempt_id: Mapped[str | None] = mapped_column(ForeignKey("execution_attempts.id"))
```

#### JSONL → Parquet compaction

A new ARQ cron job `compact_bronze_to_parquet` runs every 15 min:
- Finds `raw_events.jsonl` files for recordings with status `finalized` and no companion `raw_events.parquet` yet (or with newer JSONL mtime).
- Reads the JSONL via pyarrow, writes a single `raw_events.parquet` with snappy compression.
- Registers a new `BronzeArtifactRow` for the Parquet file.
- Leaves the JSONL in place for retention-window days, then `prune_old_artifacts` removes it.

This gives the JSONL "hot path" the operational benefits (line-by-line append, easy `tail`/grep, crash-safe) and Parquet the analytics benefits (columnar, fast DuckDB scans for cold gold computation).

#### Rules

- Bronze writers never update or delete; only `prune_old_artifacts` (cron, daily) deletes after the retention window.
- The recorder's `_on_capture` (currently in [src/rpa_recorder/browser/recorder.py:142](src/rpa_recorder/browser/recorder.py:142)) appends raw envelope JSON to `raw_events.jsonl` *before* normalization. If validation fails, the bronze record persists; only silver insertion is skipped.
- The executor's per-attempt failure handler writes screenshots/DOM/a11y through the `BronzeStore` and registers pointer rows.

#### Retention defaults

- Raw JSONL: 30 days (after Parquet exists); Parquet: 365 days.
- HAR / trace: 90 days.
- Failure screenshots / DOM / a11y: 30 days (heaviest per-event).
- LLM call JSON: 365 days (small, valuable for audit).
- All retention windows configurable via env (`RPA_BRONZE_RETENTION_*_DAYS`).

### 1.2 Silver — the existing 7 tables (no schema changes)

The current SQLAlchemy schema in [src/rpa_recorder/storage/db.py](src/rpa_recorder/storage/db.py) is already silver-shaped: validated Pydantic, normalized columns, JSON for nested payloads. **No schema changes** to existing tables. Additions only:

- New `bronze_artifacts` table (above) with FKs into existing rows.
- `LLMCallRow` already exists; attach a bronze pointer to its full prompt/response JSON.

Silver remains the operational source of truth.

### 1.3 Gold — split between hot SQLite and cold DuckDB/Parquet

Gold is **derived from silver**, **recomputed on schedule** (idempotent), and **read-only from the app's POV**. Owned by the `medallion/` package.

#### Hot gold — SQLite (or Postgres), low-latency app reads

Frequently read by the FastAPI dashboard endpoints and CLI commands. Small enough that SQLite-row reads are fine.

```python
class GoldRecordingMetricsRow(Base):       # one row per recording
    recording_id, total_runs, success_rate, avg_duration_ms,
    classifier_confidence_avg, last_replayed_at, computed_at

class GoldRunDashboardRow(Base):           # one row per (date, recording)
    date, recording_id, runs_total, runs_success, runs_failed,
    runs_recovered, computed_at
```

#### Cold gold — DuckDB on Parquet, analytics-grade

Heavy historical aggregations and time-series. Stored as Parquet under `data/gold/cold/`, queried with embedded DuckDB (no server). Naturally pairs with the bronze Parquet — DuckDB can `SELECT FROM 'data/bronze/recordings/**/raw_events.parquet'` for cross-layer queries.

```
data/gold/cold/
├── classifier_accuracy_history.parquet   # (intent, source, day, accuracy, ...)
├── llm_costs_daily.parquet               # (date, model, called_for, calls, tokens, cost)
├── training_data.parquet                 # (action_id, intent, confirmed_label, payload)
└── replay_scripts/
    └── <recording-id>/<version>.parquet  # resolved, parameterized, healed scripts
```

A `medallion/gold_cold.py` module wraps DuckDB:

```python
class ColdGold:
    def __init__(self, root: Path) -> None: ...
    def recompute_classifier_accuracy(self, conn: AsyncSession) -> None:
        # 1. Read silver via SQLAlchemy → pandas DataFrame
        # 2. duckdb.sql("SELECT ...").write_parquet("...")
        ...
    def query(self, sql: str) -> pyarrow.Table: ...
```

#### Why split?

Hot gold answers "show me the dashboard for recording X" in <10ms via SQLite. Cold gold answers "plot classifier accuracy by intent over the last 90 days" in tens of ms via DuckDB-on-Parquet without bloating the operational DB. Both are recomputed by `promote_silver_to_gold` — the only difference is destination.

#### Recomputation cadence

- **Hourly cron**: `promote_silver_to_gold` recomputes every hot + cold gold table.
- **On-demand** via CLI (`rpa medallion promote --layer gold`) and HTTP (`POST /medallion/recompute`). Useful when demoing or after editing user-confirmed labels.
- All gold writes are idempotent: hot tables are `UPSERT`-ed by primary key, cold parquet files are atomically replaced (write-temp + rename).

---

## Part 2: Page-side JavaScript organization

### 2.1 Current state

Single file at [src/rpa_recorder/assets/recorder_inject.js](src/rpa_recorder/assets/recorder_inject.js) (~7 KB, 300 lines). Loaded via `importlib.resources` in [src/rpa_recorder/browser/recorder.py:40](src/rpa_recorder/browser/recorder.py:40).

### 2.2 Target subdirectory layout (full split, all stubs created upfront)

```
src/rpa_recorder/page_scripts/
├── __init__.py              # typed loader: load("recorder/inject"), bundle(...)
├── README.md                # convention doc
├── recorder/
│   ├── inject.js            # current capture script, slimmed (uses shared)
│   ├── dom_snapshot.js      # full-DOM snapshot for silver enrichment (stub OK)
│   └── a11y_tree.js         # accessibility tree dump (stub OK)
├── replay/
│   ├── locator_healing.js   # in-page selector healing (stub for M10)
│   └── modal_detector.js    # detect unexpected modals (stub for M10)
└── shared/
    ├── selectors.js         # CSS/XPath builders (factored out of inject.js)
    └── text_utils.js        # trimText, normalize, accessibleName helpers
```

Stubs are real `.js` files that register their `window.__rpa.<name>` namespace and export a no-op entry, so:
- The loader works the same for stubs and real scripts.
- Tests import them without conditional logic.
- Recovery work (M10) and silver enrichment (later) drop in implementations without restructuring.

### 2.3 Loader pattern

```python
# src/rpa_recorder/page_scripts/__init__.py
from importlib.resources import files

def load(script: str) -> str:
    """Load a page script by relative path, e.g. 'recorder/inject'."""
    parts = script.split("/")
    leaf = parts[-1] + ".js"
    pkg = "rpa_recorder.page_scripts." + ".".join(parts[:-1])
    return files(pkg).joinpath(leaf).read_text(encoding="utf-8")

def bundle(*scripts: str) -> str:
    """Concatenate scripts in order. Convention: shared deps first."""
    return "\n;\n".join(load(s) for s in scripts)
```

Recorder migration:

```python
# browser/recorder.py
from rpa_recorder.page_scripts import bundle

script = bundle("shared/text_utils", "shared/selectors", "recorder/inject")
await self._page.add_init_script(script=script)
```

The old `assets/recorder_inject.js` file is deleted; the empty `assets/` package can stay or be removed.

### 2.4 JS module convention

Each `.js` file is an IIFE, idempotent (guarded by `window.__rpa<Name>Loaded`), dependency-free, and silently catches its own errors. Shared utilities expose themselves on `window.__rpa.shared.*`. Documented in `page_scripts/README.md`.

### 2.5 Refactor of the current inject.js

The factor-out from the existing 300-line file:

| Source (current) | Destination (new) |
|---|---|
| `trimText`, `accessibleName` | `shared/text_utils.js` |
| `uniqueCss`, `xpathOf`, `attrs`, `safeRect`, `nearbyLabels`, `inferRole`, `isVisible` | `shared/selectors.js` |
| `targetSnapshot`, `envelope`, `send`, event listeners | `recorder/inject.js` (keeps these) |

The recorder bundle uses `text_utils → selectors → inject` order so each script's globals are defined before its consumers run.

---

## Part 3: Worker queue — ARQ + Redis

### 3.1 Why ARQ

Every layer in this codebase is already async (Playwright async API, SQLAlchemy `AsyncSession`, FastAPI). ARQ jobs `await` the existing repositories and `BrowserSession` directly — no `asgiref.sync_to_async`, no thread pools, no event-loop juggling. Other queues (Celery, Dramatiq) would force one of those bridges around every job body. ARQ gives:

- Native asyncio jobs and cron
- Direct `await` on Playwright + SQLAlchemy + Anthropic
- Small dep footprint (`arq`, `redis`)
- Windows-friendly (no fork-only worker model)

### 3.2 Job catalog

| Job | Trigger | Duration | Notes |
|---|---|---|---|
| `replay_run` | enqueued from `POST /recordings/{id}/replay` or CLI | seconds–minutes | spawns its own `BrowserSession`; streams progress to `run:{run_id}` Redis channel |
| `classify_recording` | manual / on-save / cron | seconds | fan-out per action; LLM tier only when heuristic confidence < threshold |
| `generate_run_summary` | post-run, after `replay_run` finishes | seconds | one Anthropic call, writes `RunResult.summary` |
| `promote_bronze_to_silver` | on recording finalize | seconds | reads `raw_events.jsonl`, validates via Pydantic, writes silver tables |
| `compact_bronze_to_parquet` | cron (every 15 min) | seconds | converts finalized JSONL → Parquet, registers pointer row |
| `promote_silver_to_gold` | cron (hourly) + on-demand via CLI/API | seconds | recomputes hot + cold gold; idempotent |
| `prune_old_artifacts` | cron (daily) | seconds | enforces retention windows on bronze files + pointer rows |

### 3.3 Worker package layout

```
src/rpa_recorder/workers/
├── __init__.py
├── settings.py            # arq WorkerSettings: redis_settings, functions, cron_jobs
├── progress.py            # Redis pub/sub helpers (publish_progress, subscribe_run)
├── jobs/
│   ├── __init__.py
│   ├── replay.py          # replay_run
│   ├── classify.py        # classify_recording
│   ├── summary.py         # generate_run_summary
│   ├── medallion.py       # promote_bronze_to_silver, promote_silver_to_gold
│   ├── bronze_compact.py  # compact_bronze_to_parquet
│   └── prune.py           # prune_old_artifacts
└── README.md
```

### 3.4 FastAPI integration

```python
# api/routes.py
from arq import ArqRedis

@app.post("/recordings/{rid}/replay")
async def start_replay(rid: str, params: dict, pool: ArqRedis = Depends(get_arq_pool)):
    run_id = str(uuid4())
    await pool.enqueue_job("replay_run", run_id=run_id, recording_id=rid, params=params)
    return {"run_id": run_id, "status": "queued"}

@app.post("/medallion/recompute")
async def recompute_gold(pool: ArqRedis = Depends(get_arq_pool)):
    job = await pool.enqueue_job("promote_silver_to_gold")
    return {"job_id": job.job_id, "status": "queued"}

@app.websocket("/runs/{run_id}/stream")
async def stream(ws: WebSocket, run_id: str):
    await ws.accept()
    pubsub = redis.pubsub()
    await pubsub.subscribe(f"run:{run_id}")
    async for msg in pubsub.listen():
        if msg["type"] == "message":
            await ws.send_text(msg["data"])
```

Workers publish progress via `await redis.publish(f"run:{run_id}", json.dumps({...}))` from inside the replay job's per-action loop.

### 3.5 Concurrency model

- Single Redis instance (Docker: `redis:7-alpine`).
- Multiple ARQ worker processes via `WorkerSettings.max_jobs`; default 2 processes, configurable through CLI.
- **No browser sharing across jobs** — each `replay_run` invocation creates and tears down its own `BrowserSession`. Browser state is not concurrency-safe.
- DB sessions are per-job, scoped via the existing `get_session()` async context manager.

### 3.6 Local dev surface

- **`docker-compose.yml`** at repo root:
  ```yaml
  services:
    redis:
      image: redis:7-alpine
      ports: ["6379:6379"]
  ```
- **CLI additions** ([src/rpa_recorder/cli.py](src/rpa_recorder/cli.py)):
  - `rpa worker [--workers N]` — start ARQ worker(s)
  - `rpa medallion promote --layer silver|gold [--recording <id>]` — manual promotion
  - `rpa medallion compact` — manual bronze JSONL→Parquet compaction
  - `rpa medallion status` — counts and last-computed-at per layer
  - `rpa medallion prune [--dry-run]` — manual retention enforcement

---

## File-level changes

### Files to create

| Path | Purpose |
|---|---|
| `src/rpa_recorder/page_scripts/__init__.py` | `load()`, `bundle()` |
| `src/rpa_recorder/page_scripts/README.md` | conventions |
| `src/rpa_recorder/page_scripts/recorder/inject.js` | current capture, slimmed (uses shared) |
| `src/rpa_recorder/page_scripts/recorder/dom_snapshot.js` | stub |
| `src/rpa_recorder/page_scripts/recorder/a11y_tree.js` | stub |
| `src/rpa_recorder/page_scripts/replay/locator_healing.js` | stub |
| `src/rpa_recorder/page_scripts/replay/modal_detector.js` | stub |
| `src/rpa_recorder/page_scripts/shared/selectors.js` | extracted CSS/XPath/role helpers |
| `src/rpa_recorder/page_scripts/shared/text_utils.js` | extracted trim/normalize helpers |
| `src/rpa_recorder/medallion/__init__.py` | package marker |
| `src/rpa_recorder/medallion/bronze_store.py` | `BronzeStore` Protocol + `LocalFilesystemStore` |
| `src/rpa_recorder/medallion/bronze.py` | event JSONL writer, artifact pointer writer |
| `src/rpa_recorder/medallion/silver.py` | `promote_bronze_to_silver` |
| `src/rpa_recorder/medallion/gold_hot.py` | hot gold recomputation (SQLAlchemy) |
| `src/rpa_recorder/medallion/gold_cold.py` | cold gold recomputation (DuckDB → Parquet) |
| `src/rpa_recorder/medallion/compact.py` | JSONL → Parquet compaction |
| `src/rpa_recorder/medallion/paths.py` | path layout helpers (one place, used everywhere) |
| `src/rpa_recorder/medallion/retention.py` | retention policy enforcement |
| `src/rpa_recorder/workers/__init__.py` | package marker |
| `src/rpa_recorder/workers/settings.py` | `WorkerSettings` (functions + cron_jobs) |
| `src/rpa_recorder/workers/progress.py` | Redis pub/sub streaming helpers |
| `src/rpa_recorder/workers/jobs/replay.py` | `replay_run` |
| `src/rpa_recorder/workers/jobs/classify.py` | `classify_recording` |
| `src/rpa_recorder/workers/jobs/summary.py` | `generate_run_summary` |
| `src/rpa_recorder/workers/jobs/medallion.py` | `promote_bronze_to_silver`, `promote_silver_to_gold` |
| `src/rpa_recorder/workers/jobs/bronze_compact.py` | `compact_bronze_to_parquet` |
| `src/rpa_recorder/workers/jobs/prune.py` | `prune_old_artifacts` |
| `src/rpa_recorder/workers/README.md` | architecture + run instructions |
| `docker-compose.yml` | Redis service for local dev |
| `tests/test_page_scripts.py` | loader + bundle tests |
| `tests/test_bronze_store.py` | LocalFilesystemStore round-trips |
| `tests/test_medallion.py` | bronze→silver, silver→gold round-trips, idempotency |
| `tests/test_workers.py` | ARQ test runner, job-level integration |
| `tests/test_e2e_medallion.py` | record → bronze → silver → gold smoke test (`@pytest.mark.integration`) |

### Files to modify

| Path | Change |
|---|---|
| [src/rpa_recorder/config.py](src/rpa_recorder/config.py) | add `redis_url`, `bronze_root`, `gold_cold_root`, `bronze_retention_*_days`, `worker_concurrency` |
| [src/rpa_recorder/storage/db.py](src/rpa_recorder/storage/db.py) | add `BronzeArtifactRow`, `GoldRecordingMetricsRow`, `GoldRunDashboardRow` |
| [src/rpa_recorder/storage/repositories.py](src/rpa_recorder/storage/repositories.py) | add `BronzeArtifactRepository`, `GoldHotRepository` |
| [src/rpa_recorder/browser/recorder.py](src/rpa_recorder/browser/recorder.py) | switch to `page_scripts.bundle(...)`; route raw envelope writes through `BronzeStore` |
| [src/rpa_recorder/browser/executor.py](src/rpa_recorder/browser/executor.py) | write attempt artifacts via `BronzeStore`; publish per-action progress to Redis |
| [src/rpa_recorder/cli.py](src/rpa_recorder/cli.py) | add `worker`, `medallion promote/compact/status/prune` |
| [src/rpa_recorder/api/routes.py](src/rpa_recorder/api/routes.py) | enqueue ARQ jobs; pub/sub WebSocket bridge; `POST /medallion/recompute` |
| [pyproject.toml](pyproject.toml) | add deps (below); new optional `[workers]` and `[analytics]` extras |
| `.gitignore` | add `data/` |
| Delete: [src/rpa_recorder/assets/recorder_inject.js](src/rpa_recorder/assets/recorder_inject.js) | replaced by `page_scripts/recorder/inject.js` |

### Dependency additions

```toml
dependencies = [
    # ...existing...
    "arq>=0.25",
    "redis>=5.0",
    "pyarrow>=18.0",
    "duckdb>=1.1",
]

[project.optional-dependencies]
postgres = ["asyncpg>=0.30"]
# (pyarrow + duckdb are core because cold gold + bronze compaction depend on them)
```

If keeping `pyarrow` + `duckdb` out of the default install matters for footprint, move them to a new `[analytics]` optional extra and have `medallion/gold_cold.py` and `medallion/compact.py` import lazily.

---

## Milestone integration (Option A — interleave)

Insert two new milestones into the existing M1–M14 sequence, so artifacts land in their final home from day one and downstream code (executor, FastAPI) reads from the right place without retrofit.

| New milestone | Position | Contents |
|---|---|---|
| **M5.5 — Page scripts reorg + bronze layer** | between M5 (Storage) and M6 (Executor) | `page_scripts/` full split + loader + recorder migration; `medallion/bronze_store.py`, `medallion/bronze.py`, `medallion/paths.py`; `BronzeArtifactRow` + repository; recorder writes raw envelopes to bronze JSONL; tests for loader, store, bronze writes |
| **M11.5 — Workers + medallion promotion** | between M11 (Confirmation) and M12 (FastAPI) | ARQ + Redis dependency add; `workers/` package with all 7 jobs; `medallion/silver.py`, `medallion/gold_hot.py`, `medallion/gold_cold.py`, `medallion/compact.py`, `medallion/retention.py`; CLI additions; `docker-compose.yml`; tests for bronze→silver, silver→gold, compaction, pruning, ARQ job execution |

M6 (Executor) and M12 (FastAPI) are then aware of the medallion layer from the moment they're built — no retrofit pass needed.

---

## Verification

End-to-end checks for both milestones, runnable as part of the milestone exit criteria.

**M5.5 (page scripts + bronze):**

1. **Loader works:** `uv run python -c "from rpa_recorder.page_scripts import load; print(len(load('recorder/inject')))"` returns >0 for every script in the tree (including stubs).
2. **Recorder still works:** existing recorder integration test passes after migration to `bundle(...)`.
3. **Bronze writes happen:** record a session against a fixture page; assert `data/bronze/recordings/<id>/raw_events.jsonl` has one line per envelope; assert `bronze_artifacts` table has a row whose `sha256` matches `hashlib.sha256(file_bytes).hexdigest()`.
4. **Failure artifacts route correctly:** trigger an executor failure; assert screenshot/DOM/a11y land under `data/bronze/runs/<run_id>/attempts/<n>/` and pointer rows exist.

**M11.5 (workers + medallion):**

5. **Silver promotion:** `uv run rpa medallion promote --layer silver --recording <id>` reads bronze JSONL and writes silver row counts that match envelope counts.
6. **Bronze compaction:** `uv run rpa medallion compact` produces `raw_events.parquet`; `duckdb -c "SELECT COUNT(*) FROM 'data/bronze/recordings/<id>/raw_events.parquet'"` matches JSONL line count.
7. **Hot gold:** `uv run rpa medallion promote --layer gold` populates `gold_recording_metrics` and `gold_run_dashboard`; second invocation is a no-op (row counts unchanged, `computed_at` advances).
8. **Cold gold:** the same call writes `data/gold/cold/classifier_accuracy_history.parquet` etc.; `duckdb -c "SELECT * FROM 'data/gold/cold/llm_costs_daily.parquet' LIMIT 5"` returns rows.
9. **Workers + replay:**
   - `docker compose up -d redis`
   - `uv run rpa worker --workers 2`
   - `uv run rpa replay <recording-id>` (or `POST /recordings/{id}/replay`) returns a `run_id`
   - `ws://localhost:8000/runs/{run_id}/stream` streams progress events
   - Two simultaneous replays of different recordings finish without contention
10. **Cron jobs fire:** schedule `promote_silver_to_gold` every minute in dev; observe `computed_at` advancing on each tick.
11. **On-demand gold:** `POST /medallion/recompute` returns a job_id; assert hot gold row `computed_at` advances within seconds.
12. **Pruning enforces retention:** insert a backdated bronze artifact, run `rpa medallion prune`; confirm file + row removed.

End-to-end smoke test: `tests/test_e2e_medallion.py` (marked `@pytest.mark.integration`) records a 3-action session on a fixture page, finalizes it, runs the full bronze→silver→gold pipeline through workers, and asserts a hot-gold metrics row exists with the expected counts.

---

## Decisions log

| Question | Decision |
|---|---|
| Worker queue | **ARQ + Redis** — native asyncio, smallest dep footprint, Windows-friendly. |
| Bronze storage format | **JSONL hot + Parquet on promotion.** Recorder appends JSONL live; cron compaction produces Parquet for cold-gold/DuckDB queries. |
| Cloud-readiness of bronze | **`BronzeStore` Protocol now, `LocalFilesystemStore` v1.** S3/MinIO can drop in later without touching writers. |
| Gold storage | **Split: hot tables in SQLite (alongside silver), cold tables as Parquet under DuckDB.** |
| Gold cadence | **Hourly cron + on-demand** via CLI (`rpa medallion promote --layer gold`) and HTTP (`POST /medallion/recompute`). |
| JS reorganization | **Full split with all stub files now** — `recorder/`, `replay/`, `shared/` subdirs created upfront with stub `dom_snapshot.js`, `a11y_tree.js`, `locator_healing.js`, `modal_detector.js`. |
| Milestone placement | **Interleave (Option A):** M5.5 (page scripts + bronze) and M11.5 (workers + medallion promotion). |
| Bronze retention defaults | JSONL 30d (after Parquet exists); Parquet 365d; HAR/trace 90d; failure artifacts 30d; LLM call JSON 365d. All configurable. |
