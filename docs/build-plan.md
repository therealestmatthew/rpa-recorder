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
| M1 | Project scaffold | ✅ done | [m1-project-scaffold.md](m1-project-scaffold.md) |
| M2 | Data models | ✅ done | [m2-data-models.md](m2-data-models.md) |
| M3 | BrowserSession | ✅ done | [m3-browser-session.md](m3-browser-session.md) |
| M4 | Recorder + JS | ✅ done | [m4-recorder.md](m4-recorder.md) |
| M5 | Storage layer | ✅ done | [m5-storage-layer.md](m5-storage-layer.md) |
| M6 | Executor | ✅ done | [m6-executor.md](m6-executor.md) |
| **M6.5** | **Page scripts + bronze layer** *(retrofit)* | 🆕 pending | [m6.5-page-scripts-and-bronze.md](m6.5-page-scripts-and-bronze.md) |
| M7 | Heuristic classifier | 🟡 in progress | [m7-heuristic-classifier.md](m7-heuristic-classifier.md) |
| M8 | CLI commands | ⬜ pending | [m8-cli-commands.md](m8-cli-commands.md) |
| M9 | LLM classifier | ⬜ pending | [m9-llm-classifier.md](m9-llm-classifier.md) |
| M10 | Recovery engine | ⬜ pending | [m10-recovery-engine.md](m10-recovery-engine.md) |
| M11 | Confirmation workflow | ⬜ pending | [m11-confirmation-workflow.md](m11-confirmation-workflow.md) |
| **M11.5** | **Workers + medallion promotion** | 🆕 pending | [m11.5-workers-and-medallion-promotion.md](m11.5-workers-and-medallion-promotion.md) |
| M12 | FastAPI control plane | ⬜ pending | [m12-fastapi-control-plane.md](m12-fastapi-control-plane.md) |
| M13 | GitHub Actions CI | ⬜ pending | [m13-github-actions-ci.md](m13-github-actions-ci.md) |
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
