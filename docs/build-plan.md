# RPA Recorder — Master Build Plan

> Index of every milestone, its current status, and how the medallion data lake
> + ARQ worker queue thread through the project. This document **supersedes**
> the milestone-by-milestone files where they disagree on sequencing or
> integration; the milestone files own their own scope detail.
>
> Deep design reference for medallion + workers: [medallion-and-workers.md](medallion-and-workers.md).
> Original canonical spec: [.claude/plans/bootstrap.md](../.claude/plans/bootstrap.md).

## Sequence

| # | Milestone | Status | Doc |
|---|---|---|---|
| M1 | Project scaffold | ✅ done | [_archive/m1-project-scaffold.md](_archive/m1-project-scaffold.md) |
| M2 | Data models | ✅ done | [_archive/m2-data-models.md](_archive/m2-data-models.md) |
| M3 | BrowserSession | ✅ done | [_archive/m3-browser-session.md](_archive/m3-browser-session.md) |
| M4 | Recorder + JS | ✅ done | [_archive/m4-recorder.md](_archive/m4-recorder.md) |
| M5 | Storage layer | ✅ done | [_archive/m5-storage-layer.md](_archive/m5-storage-layer.md) |
| M6 | Executor | ✅ done | [_archive/m6-executor.md](_archive/m6-executor.md) |
| **M6.5** | **Page scripts + bronze layer** *(retrofit)* | ✅ done | [m6.5-page-scripts-and-bronze.md](m6.5-page-scripts-and-bronze.md) |
| M7 | Heuristic classifier | ✅ done | [m7-heuristic-classifier.md](m7-heuristic-classifier.md) |
| M8 | CLI commands | ✅ done | [m8-cli-commands.md](m8-cli-commands.md) |
| M9 | LLM classifier | ✅ done | [m9-llm-classifier.md](m9-llm-classifier.md) |
| M10 | Recovery engine | ✅ done | [m10-recovery-engine.md](m10-recovery-engine.md) |
| M11 | Confirmation workflow | ✅ done | [m11-confirmation-workflow.md](m11-confirmation-workflow.md) |
| **M11.5** | **Workers + medallion promotion** | 🆕 pending | [m11.5-workers-and-medallion-promotion.md](m11.5-workers-and-medallion-promotion.md) |
| M12 | FastAPI control plane | ✅ done *(Protocol-seam variant)* | [m12-fastapi-control-plane.md](m12-fastapi-control-plane.md) |
| M13 | GitHub Actions CI | ✅ done | [m13-github-actions-ci.md](m13-github-actions-ci.md) |
| M14 | Documentation polish | ⬜ pending | [m14-documentation-polish.md](m14-documentation-polish.md) |

## Why two new milestones

M5 and M6 are already shipped, so the originally proposed "M5.5 interleave" can't physically happen. The medallion + worker work splits cleanly along the natural seam between *capture* and *processing*:

- **M6.5 (retrofit)** owns the bronze foundation: `page_scripts/` reorganization of M4's inject script, `BronzeStore` Protocol with `LocalFilesystemStore`, `bronze_artifacts` pointer table, and recorder/executor write-path changes that route raw envelopes, screenshots, DOM dumps, and a11y snapshots through the store. This must precede M9/M10/M12 because they all reference the bronze contracts.
- **M11.5** owns the processing side: ARQ + Redis, silver promotion, gold (split between hot SQLite and cold DuckDB-on-Parquet), JSONL→Parquet compaction, retention pruning, and the cron schedule. This must precede M12 because the FastAPI control plane enqueues into the worker layer rather than spawning `asyncio.create_task` itself.

## How medallion + workers thread through

| Milestone | Integration |
|---|---|
| M6.5 | **Owns** `BronzeStore`, `LocalFilesystemStore`, `bronze_artifacts` table, JS subdir split, recorder/executor bronze writes. |
| M7 | None (heuristic is pure-Python). Confirmed labels from M11 later flow into `gold_training_data.parquet`. |
| M8 | Adds `rpa worker`, `rpa medallion promote/compact/status/prune` subcommands. Existing `record`/`replay`/`classify` are unchanged but `replay` gains a `--queue` flag that enqueues into ARQ instead of running in-process. |
| M9 | Every LLM call writes a JSON blob to `data/bronze/llm/<call-id>.json` via `BronzeWriter.write_llm_call(...)` and registers a `bronze_artifacts` pointer alongside the existing `llm_calls` row. |
| M10 | `LLMReselectStrategy` writes its prompt/response to bronze; on success the corrected `ElementSelector` becomes part of `RecoveryAction` and (via M11.5) the `gold_replay_scripts` Parquet. |
| M11 | After a confirmation pass completes, the CLI triggers an on-demand `promote_silver_to_gold` enqueue so dashboards reflect the new labels immediately. |
| M11.5 | **Owns** `workers/` package, all 7 ARQ jobs, silver + gold promotion code, retention pruning, cron schedule, Redis pub/sub helpers. |
| M12 | Replays become `replay_run` jobs enqueued via `arq.create_pool().enqueue_job(...)`. WebSocket bridges to Redis pub/sub on `run:{run_id}` channels. New `POST /medallion/recompute` endpoint. |
| M13 | Adds a `redis:7-alpine` services block in CI. New marker `worker` joins `llm` / `integration` for tests that need Redis up. |
| M14 | README adds a "Medallion data layout" section; `docs/architecture.md` covers the full bronze→silver→gold + worker fanout diagram. |

## Concurrency conventions

These rules apply across every milestone. The medallion + worker plan codifies them; M6.5 and M11.5 own implementation details. When a milestone introduces a new concurrency primitive (queue, semaphore, lock, fan-out), it must update this table and call out the rule in its own pitfalls section.

| Convention | Rule | Owner |
|---|---|---|
| Async everywhere | No blocking I/O on the event loop. Sync libraries (DuckDB, pyarrow heavy ops) wrap in `asyncio.to_thread`. | All |
| Engine pooling | One `AsyncEngine` per process, shared across coroutines via the engine's pool. Sessions are per-operation (created via `get_session()` context manager) and never reused. | M5 |
| Browser per replay | Each `replay_run` invocation creates and tears down its own `BrowserSession`. Browser state is not concurrency-safe. | M3, M11.5 |
| Bounded queues | Producer-consumer between high-rate event sources and durable writers (e.g., Recorder → bronze). Bounded queues with backpressure (drops logged, never silently lost). | M6.5 |
| Structured concurrency | `asyncio.TaskGroup` for fan-out so one task's failure cleanly cancels siblings. Catch `ExceptionGroup` at the boundary. | M9, M11.5 |
| Semaphores for caps | Cap parallel calls to expensive resources (LLM API, browser launches) with `asyncio.Semaphore`. Per-instance, not module-global (event-loop-bound). | M9, M11.5 |
| Distributed locks | Redis `SET NX EX` to ensure only one worker runs `promote_silver_to_gold` at a time. | M11.5 |
| Job retry policy | Idempotent jobs (silver/gold promotion, compaction, prune): `max_tries=3`. Non-idempotent jobs (`replay_run`): `max_tries=1`. | M11.5 |
| Queue separation | Browser-heavy jobs (`replay_queue`, `max_jobs=2`) and IO-bound jobs (`medallion_queue`, `max_jobs=10`) run on separate ARQ queues. | M11.5 |
| Graceful shutdown | Workers drain in-flight jobs on SIGTERM (default 60 s `shutdown_timeout`). Recorder drains its bronze queue on `stop()`. | M6.5, M11.5 |
| Backpressure at API edge | FastAPI rejects new replays with HTTP 429 when `pool.queue_size() > Config.max_queue_depth`. | M12 |
| SQLite WAL mode | `PRAGMA journal_mode=WAL`, `PRAGMA busy_timeout=5000` enabled in `init_db()`. Above ~2 concurrent writers, recommend Postgres. | M5, M11.5 |
| Per-job logging | `structlog.contextvars.bind_contextvars(job_id=..., queue=...)` at each job entry for filterable logs. | M11.5 |
| LLM concurrency cap | Per-`LLMClassifier` `asyncio.Semaphore(Config.llm_max_concurrency)` (default 5). Total across workers = `worker_count × llm_max_concurrency`. | M9 |
| Disable SDK retries | Anthropic SDK `max_retries=0` so `RetryPolicy` is the sole retry layer. | M9 |

## Reading order for a contributor coming in cold

1. [README.md](../README.md) — elevator pitch (populated in M14).
2. [.claude/plans/bootstrap.md](../.claude/plans/bootstrap.md) — original canonical spec.
3. This file — sequence + integration map.
4. [medallion-and-workers.md](medallion-and-workers.md) — medallion + worker design depth.
5. The individual `m*.md` files in numeric order (m6.5 between m6 and m7; m11.5 between m11 and m12).

## Conventions for milestone docs

Adopted from M1–M6 as the standard. Each milestone doc must include:

- **Goal** — one paragraph; why this exists in the build order.
- **Files** — exact paths to create / modify / delete, including tests.
- **Public API** — full Python signatures with type annotations matching strict mypy + ruff (`from __future__ import annotations` is **not** used in this project; runtime-needed types stay runtime-imported, type-only imports under `if TYPE_CHECKING:`).
- **Behavior** — bullet-by-bullet of what each function does, including edge cases, raised exceptions, and tricky ordering / async concurrency notes.
- **Integration points** — file/line-ish references to where this milestone plugs into earlier ones.
- **Models / DB rows used** — explicit list of which Pydantic models and SQLAlchemy rows are read or written.
- **Tests** — concrete `tests/test_*.py` filenames, named test functions, what each asserts, fixtures needed.
- **Known pitfalls** — anything that would otherwise be discovered by trial and error (ruff TC002 vs Playwright introspection, PEP 758 except-paren behavior in 3.14, asyncio handler ordering, etc.).
- **Commit message** — already present where applicable; refine the body if scope crystallized.

When the spec at [.claude/plans/bootstrap.md](../.claude/plans/bootstrap.md) contradicts what M1–M6 actually shipped (e.g., the spec lists 6 storage tables; M5 ships 7 including `llm_calls`), trust the M5 doc and update the milestone plan to match.
