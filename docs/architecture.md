# Architecture

How `rpa-recorder` fits together. One section per layer in data-flow
order, then three cross-cutting sections (concurrency, full data flow,
adding a new layer). Each layer section follows the same shape so a new
layer drops in by adding a section.

For the original 14-milestone design intent, see
[`.claude/plans/bootstrap.md`](../.claude/plans/bootstrap.md). For the
master milestone index, see [`build-plan.md`](build-plan.md).

## Layer shape

Every layer section follows this template:

> **Purpose** (one sentence) <br>
> **Key files** (links into `src/rpa_recorder/`) <br>
> **Depends on** (which earlier layers it uses) <br>
> **Extension points** (where new behavior plugs in) <br>
> **See also** (link to the milestone doc that introduced it)

---

## Capture (page-side JS)

**Purpose** — Run JavaScript in the page context to emit a structured
event for every interaction the operator performs.

**Key files** —
[`page_scripts/recorder/inject.js`](../src/rpa_recorder/page_scripts/),
[`page_scripts/shared/`](../src/rpa_recorder/page_scripts/),
[`page_scripts/README.md`](../src/rpa_recorder/page_scripts/README.md).

**Depends on** — Playwright; the `Recorder` class
([`browser/recorder.py`](../src/rpa_recorder/browser/recorder.py))
loads the scripts.

**Extension points** — New scripts drop into
`page_scripts/{recorder,replay,shared}/` following the IIFE +
`window.__rpaXLoaded` guard convention. New shared utilities go under
`window.__rpa.shared.<name>`.

**See also** — [`m6.5-page-scripts-and-bronze.md`](m6.5-page-scripts-and-bronze.md).

## Bronze (raw artifacts)

**Purpose** — Append-only on-disk store for raw capture artifacts.
Operator-private; preserves `is_sensitive=True` payloads byte-for-byte.

**Key files** —
[`medallion/bronze_store.py`](../src/rpa_recorder/medallion/bronze_store.py),
[`medallion/bronze.py`](../src/rpa_recorder/medallion/bronze.py),
[`medallion/paths.py`](../src/rpa_recorder/medallion/paths.py),
[`medallion/README.md`](../src/rpa_recorder/medallion/README.md).
The `bronze_artifacts` silver-side pointer table lives in
[`storage/`](../src/rpa_recorder/storage/).

**Depends on** — Filesystem (default `LocalFilesystemStore`) +
silver DB for the pointer table.

**Extension points** — Implement the `BronzeStore` Protocol for a
remote store (S3 / MinIO future). Add a new artifact type by extending
`BronzeWriter` with a `write_<kind>(...)` method and a corresponding
`bronze_artifacts.type` value.

**See also** — [ADR-0001](../.claude/plans/adr/0001-medallion-bronze-silver-gold-split.md),
[`m6.5-page-scripts-and-bronze.md`](m6.5-page-scripts-and-bronze.md).

## Silver (validated rows)

**Purpose** — Typed, validated rows backing the application. Read by
the CLI, executor, and FastAPI surface.

**Key files** —
[`storage/db.py`](../src/rpa_recorder/storage/db.py),
[`storage/repositories.py`](../src/rpa_recorder/storage/repositories.py),
[`storage/README.md`](../src/rpa_recorder/storage/README.md).
Pydantic shapes live in [`models/`](../src/rpa_recorder/models/).

**Depends on** — Bronze (as a promotion source for the M11.5 silver
promotion job); SQLAlchemy 2.0 + aiosqlite (default) or asyncpg
(`postgres` extra).

**Extension points** — Add a new `<Name>Repository` in
`repositories.py` for a new table. Document the new env vars in
[`configuration.md`](configuration.md). If the table feeds gold, wire
a promotion fn into [`medallion/`](../src/rpa_recorder/medallion/).

**See also** — [`_archive/m5-storage-layer.md`](_archive/m5-storage-layer.md).

## Gold (analytics)

**Purpose** — Analytics-shaped aggregates. Hot half (SQLite) backs
dashboard endpoints; cold half (DuckDB-on-Parquet) backs training data
exports and analytical queries.

**Key files** —
[`medallion/gold_hot.py`](../src/rpa_recorder/medallion/gold_hot.py),
[`medallion/gold_cold.py`](../src/rpa_recorder/medallion/gold_cold.py),
[`medallion/compact.py`](../src/rpa_recorder/medallion/compact.py),
[`medallion/retention.py`](../src/rpa_recorder/medallion/retention.py).

**Depends on** — Silver (promotion source) + workers (cron + on-demand
promotion jobs).

**Extension points** — Add a hot table in `gold_hot.py` with a
`promote_to_<name>` fn, or a cold Parquet path in `gold_cold.py` with a
DuckDB INSERT-SELECT. Wire the new fn into `promote_silver_to_gold`
in [`workers/`](../src/rpa_recorder/workers/).

**See also** — [`m11.5-workers-and-medallion-promotion.md`](m11.5-workers-and-medallion-promotion.md),
[`medallion-and-workers.md`](medallion-and-workers.md).

## Heuristic classifier

**Purpose** — Pure-Python first tier of intent classification. Filters
drop noise, normalizers rewrite to canonical shape, classifiers assign
a `SemanticIntent` with a confidence score.

**Key files** —
[`classifier/heuristic/engine.py`](../src/rpa_recorder/classifier/heuristic/engine.py),
[`classifier/heuristic/protocol.py`](../src/rpa_recorder/classifier/heuristic/protocol.py),
[`classifier/README.md`](../src/rpa_recorder/classifier/README.md).

**Depends on** — `RecordedAction` + `SemanticIntent` from
[`models/`](../src/rpa_recorder/models/).

**Extension points** — Three axes:
[`filters/`](../src/rpa_recorder/classifier/heuristic/filters/),
[`normalizers/`](../src/rpa_recorder/classifier/heuristic/normalizers/),
[`classifiers/`](../src/rpa_recorder/classifier/heuristic/classifiers/).
Add a module + register in the axis's `__init__.py`.

**See also** — [`m7-heuristic-classifier.md`](m7-heuristic-classifier.md).

## LLM classifier

**Purpose** — Second tier of classification. Hybrid orchestrator
escalates to the LLM when heuristic confidence is below the threshold.

**Key files** —
[`classifier/llm/hybrid.py`](../src/rpa_recorder/classifier/llm/hybrid.py),
[`classifier/llm/classifier.py`](../src/rpa_recorder/classifier/llm/classifier.py),
[`classifier/llm/protocol.py`](../src/rpa_recorder/classifier/llm/protocol.py),
[`classifier/llm/cost.py`](../src/rpa_recorder/classifier/llm/cost.py).

**Depends on** — Heuristic classifier (for confidence-based escalation),
Anthropic SDK, bronze (for per-call audit blob), silver `llm_calls`
(for the audit row).

**Extension points** — Three axes:
[`backends/`](../src/rpa_recorder/classifier/llm/backends/),
[`prompts/`](../src/rpa_recorder/classifier/llm/prompts/),
[`parsers/`](../src/rpa_recorder/classifier/llm/parsers/).

**See also** — [`m9-llm-classifier.md`](m9-llm-classifier.md).

## Recovery

**Purpose** — When the executor can't resolve a selector or an action
fails, run strategies in priority order until one succeeds. The
corrected `ElementSelector` flows into the action result and into the
gold replay scripts so future replays self-heal.

**Key files** —
[`recovery/engine.py`](../src/rpa_recorder/recovery/engine.py),
[`recovery/protocol.py`](../src/rpa_recorder/recovery/protocol.py),
[`recovery/strategies/`](../src/rpa_recorder/recovery/strategies/),
[`recovery/README.md`](../src/rpa_recorder/recovery/README.md).

**Depends on** — Executor ([`browser/`](../src/rpa_recorder/browser/))
triggers recovery; `llm_reselect` reuses the LLM tier from
[`classifier/llm/`](../src/rpa_recorder/classifier/llm/).

**Extension points** — Add a strategy module under
`recovery/strategies/` and register with a priority. Recursion is
bounded by `Config.recovery_max_depth`.

**See also** — [`m10-recovery-engine.md`](m10-recovery-engine.md).

## Confirmation

**Purpose** — Operator-driven review of classifier output before it
becomes training data. Three-axis pipeline (filter → mode → renderer).

**Key files** —
[`confirmation/runner.py`](../src/rpa_recorder/confirmation/runner.py),
[`confirmation/protocol.py`](../src/rpa_recorder/confirmation/protocol.py),
[`confirmation/README.md`](../src/rpa_recorder/confirmation/README.md).

**Depends on** — Silver `recorded_actions`, LLM tier outputs, gold
promotion (after a session, kicks `promote_silver_to_gold`).

**Extension points**
([`filters/`](../src/rpa_recorder/confirmation/filters/),
[`modes/`](../src/rpa_recorder/confirmation/modes/),
[`renderers/`](../src/rpa_recorder/confirmation/renderers/)).

**See also** — [`m11-confirmation-workflow.md`](m11-confirmation-workflow.md).

## Workers (ARQ + Redis)

**Purpose** — Run replays and medallion promotion jobs off the FastAPI
loop. Two `WorkerSettings` classes split browser-heavy and IO-bound
queues so they don't starve each other.

**Key files** —
[`workers/`](../src/rpa_recorder/workers/),
[`workers/README.md`](../src/rpa_recorder/workers/README.md).

**Depends on** — Redis (broker + pub/sub + cache), bronze + silver +
gold (jobs read and write all three tiers).

**Extension points** — Add a job module under `workers/` and register
in `workers/settings.py`. Cron jobs go on `MedallionWorkerSettings`.
Idempotent jobs use `max_tries=3`; non-idempotent (`replay_run`) use
`max_tries=1`.

**See also** — [ADR-0003](../.claude/plans/adr/0003-arq-over-celery-for-workers.md),
[`m11.5-workers-and-medallion-promotion.md`](m11.5-workers-and-medallion-promotion.md).

## CLI (Typer)

**Purpose** — Operator entry point for every operational concern. One
file per subcommand.

**Key files** —
[`cli/app.py`](../src/rpa_recorder/cli/app.py),
[`cli/commands/`](../src/rpa_recorder/cli/commands/),
[`cli/README.md`](../src/rpa_recorder/cli/README.md).

**Depends on** — Every operational layer (record → recorder, replay →
queue pool, classify → classifier, confirm → confirmation, serve →
api, worker → workers, medallion → medallion).

**Extension points** — Add `commands/<name>.py` and register in
`commands/__init__.py`.

**See also** — [`m8-cli-commands.md`](m8-cli-commands.md).

## API (FastAPI)

**Purpose** — HTTP control plane. Per-resource routers, fixed middleware
stack, WebSocket bridge to Redis pub/sub for live replay progress.

**Key files** —
[`api/app.py`](../src/rpa_recorder/api/app.py),
[`api/routers/`](../src/rpa_recorder/api/routers/),
[`api/middleware/`](../src/rpa_recorder/api/middleware/),
[`api/streaming/manager.py`](../src/rpa_recorder/api/streaming/manager.py),
[`api/README.md`](../src/rpa_recorder/api/README.md).

**Depends on** — `QueuePool` Protocol seam to workers
([`queues/`](../src/rpa_recorder/queues/)), Redis (pub/sub bridge),
silver DB (reads), bronze (large-payload references in responses).

**Extension points** — Add `routers/<resource>.py` and
`schemas/<resource>.py`; register in `app.py`. Enqueue via
`Depends(get_queue_pool)`; never import a backend directly.

**See also** — [ADR-0002](../.claude/plans/adr/0002-protocol-seam-for-queue-pool.md),
[`m12-fastapi-control-plane.md`](m12-fastapi-control-plane.md).

---

## Concurrency model

The full table of project-wide concurrency conventions lives in
[`build-plan.md` §"Concurrency conventions"](build-plan.md#concurrency-conventions)
— that's the source of truth. Highlights:

- **Async everywhere.** No blocking I/O on the event loop. Sync libs
  (DuckDB, heavy pyarrow) wrap in `asyncio.to_thread`.
- **One `AsyncEngine` per process.** Sessions are per-operation,
  acquired through `get_session()` and never reused.
- **Browser per replay.** `BrowserSession` is created and torn down per
  replay run. ARQ caps `replay_queue` at `max_jobs=2`.
- **Bounded queues with backpressure.** Recorder → bronze writer uses
  a bounded `asyncio.Queue` with overflow logging. FastAPI returns 429
  when `pool.queue_size() > Config.max_queue_depth`.
- **Structured concurrency.** `asyncio.TaskGroup` for fan-out so one
  task's failure cleanly cancels siblings.
- **Per-instance semaphores.** `LLMClassifier` owns an
  `asyncio.Semaphore(Config.llm_max_concurrency)` (default 5). Total
  concurrency = `worker_count × this`.
- **Distributed locks.** Redis `SET NX EX` ensures only one worker runs
  `promote_silver_to_gold` at a time.
- **Idempotent vs non-idempotent retries.** Promotions retry 3×;
  `replay_run` retries 1× (browser side effects).
- **SQLite WAL mode.** `journal_mode=WAL`, `busy_timeout=5000`. Above
  ~2 concurrent writers, prefer Postgres via the `postgres` extra.

## Data flow

```
Browser event
  ↓ (page_scripts/recorder/inject.js)
Recorder bounded queue
  ↓ (BronzeWriter)
data/bronze/<recording-id>/events.jsonl + screenshots/ + dom/ + ...
  ↓ (M11.5: promote_bronze_to_silver job)
silver tables (recordings, recorded_actions, network_events, ...)
  ↓ (classify CLI / job)
heuristic classifier → confidence < 0.7 → LLM tier
  ↓ (rpa replay / POST /replay/{id})
Executor + Recovery
  ↓ (writes execution_attempts, action_executions)
silver run_results
  ↓ (M11.5: promote_silver_to_gold job, also triggered after confirm)
gold_hot SQLite (dashboard) + gold_cold Parquet (training data)
  ↓ (FastAPI dashboard endpoints / DuckDB queries)
Operator + future-replay self-healing
```

Each arrow is owned by exactly one milestone — see
[`build-plan.md` §"How medallion + workers thread through"](build-plan.md#how-medallion--workers-thread-through).

## Adding a new layer

Worked example — say we want a "Visual diff" layer that screenshots each
action, diffs against a baseline, and surfaces regressions:

1. **Capture changes** — add a new page-side script under
   [`page_scripts/replay/`](../src/rpa_recorder/page_scripts/) (a no-op
   capture; visual diffing happens at the host).
2. **Bronze artifact type** — add `screenshot_diff` to `bronze_artifacts.type`,
   teach `BronzeWriter` to `write_diff(...)`. Update
   [`medallion/README.md`](../src/rpa_recorder/medallion/README.md).
3. **Silver schema** — add a `visual_diffs` table in
   [`storage/repositories.py`](../src/rpa_recorder/storage/repositories.py).
4. **Promotion** — add a `promote_visual_diffs_to_gold` fn in
   [`medallion/gold_cold.py`](../src/rpa_recorder/medallion/gold_cold.py)
   (large; cold). Wire into the `promote_silver_to_gold` job.
5. **Gold table** — Parquet under `data/gold/cold/visual_diffs/`.
6. **CLI** — `commands/visual_diff.py` for ad-hoc exports.
7. **API** — new router in `api/routers/visual_diff.py`.
8. **Architecture doc** — add a "Visual diff" section to this file
   following the layer template.
9. **Glossary** — define `VisualDiff` and `Baseline` in
   [`glossary.md`](glossary.md).
10. **Configuration** — add new env vars (e.g.,
    `RPA_VISUAL_DIFF_TOLERANCE`) to
    [`configuration.md`](configuration.md).
11. **Milestone doc** — `docs/m<N>-visual-diff.md` from
    [`.claude/plans/TEMPLATE.md`](../.claude/plans/TEMPLATE.md).

The seams are explicit. No layer requires modifying another's internals.
