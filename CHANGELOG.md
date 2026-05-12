# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Documentation set: README, LICENSE (MIT), CHANGELOG, CONTRIBUTING, SECURITY.
- `docs/architecture.md` — layered walkthrough (capture → bronze → silver → gold → workers → API).
- `docs/configuration.md` — exhaustive `RPA_*` env var reference.
- `docs/glossary.md` — domain term definitions.
- `.claude/plans/README.md` — plan library index.
- `.claude/plans/TEMPLATE.md` — milestone plan template.
- ADRs: medallion bronze/silver/gold split, Protocol-seam queue pool, ARQ over Celery.
- Module READMEs for `api`, `browser`, `classifier`, `cli`, `confirmation`, `medallion`, `models`, `queues`, `recovery`, `storage`.

## [0.2.0] — 2026-04

### Added

- M11.5 ARQ + Redis workers; silver and gold promotion (hot SQLite + cold DuckDB-on-Parquet); JSONL→Parquet compaction; retention pruning.
- M12 modular FastAPI control plane: per-resource routers, middleware stack (request id, structured logging, rate limit, backpressure), WebSocket manager bridging Redis pub/sub.
- `QueuePool` Protocol with `InProcessQueuePool` and `ArqQueuePool` implementations.
- M13 GitHub Actions CI with composite actions and marker-based job sharding.

## [0.1.0] — 2026-01

### Added

- M1 project scaffold (uv, pyproject, ruff, mypy, pytest).
- M2 Pydantic v2 data models: `RecordedAction`, `Recording`, `RunResult`, `LLMCall`, related types.
- M3 `BrowserSession` async context manager.
- M4 `Recorder` with page-side JS capture.
- M5 Async SQLAlchemy 2.0 storage with seven silver tables.
- M6 `Executor` with multi-strategy selector resolution.
- M6.5 `page_scripts/` subdir split + bronze layer (`BronzeStore` Protocol, `BronzeWriter`, `bronze_artifacts` table, bounded producer/consumer queue).
- M7 Modular heuristic classifier (filter / normalize / classify pipeline).
- M8 Modular Typer CLI: `record`, `replay`, `classify`, `confirm`, `list`, `show`, `serve`, `worker`, `medallion`.
- M9 Pluggable LLM tier: Anthropic backend, prompt and parser modules, retry with exponential backoff, response cache, daily budget guard, hybrid heuristic-then-LLM merge strategy.
- M10 Modular recovery engine: `wait_and_retry`, `scroll_into_view`, `dismiss_modal`, `frame_switch`, `llm_reselect` strategies with verifier.
- M11 Modular confirmation workflow: filter / mode / renderer pipeline.

[Unreleased]: https://github.com/therealestmatthew/rpa-recorder/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/therealestmatthew/rpa-recorder/releases/tag/v0.2.0
[0.1.0]: https://github.com/therealestmatthew/rpa-recorder/releases/tag/v0.1.0
