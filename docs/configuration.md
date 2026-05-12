# Configuration

Every runtime knob in `rpa-recorder` is a `Config` field in
[`src/rpa_recorder/config.py`](../src/rpa_recorder/config.py) loaded from
`.env` and environment variables. Field names are uppercased and prefixed
with `RPA_` (e.g., `database_url` → `RPA_DATABASE_URL`).

When a `Config` field is added or changed in `config.py`, this table must
be updated in the same PR — see [`CONTRIBUTING.md`](../CONTRIBUTING.md).

## Database and storage paths

| Var | Type | Default | Description | Owner |
|---|---|---|---|---|
| `RPA_DATABASE_URL` | str | `sqlite+aiosqlite:///rpa.db` | SQLAlchemy connection URL. `postgresql+asyncpg://...` requires the `postgres` extra. | M5 |
| `RPA_RECORDINGS_DIR` | path | `recordings` | Per-recording artifacts root (legacy; predates bronze). | M2 |
| `RPA_SCREENSHOTS_DIR` | path | `screenshots` | Failure screenshots from replay. | M6 |
| `RPA_TRACES_DIR` | path | `traces` | Playwright trace files for failed replays. | M6 |
| `RPA_DOM_DIR` | path | `dom` | DOM snapshots from replay failures. | M6 |
| `RPA_STORAGE_STATE_DIR` | path | `storage_state` | Persisted Playwright `storage_state.json` per recording. | M3 |

## Bronze layer

| Var | Type | Default | Description | Owner |
|---|---|---|---|---|
| `RPA_BRONZE_ROOT` | path | `data/bronze` | Bronze tier root. JSONL events, screenshots, DOM dumps, HAR, LLM blobs land here. | M6.5 |
| `RPA_BRONZE_QUEUE_SIZE` | int | `1000` | Bounded queue cap between recorder and bronze writer. Drops on overflow are logged, never silently lost. | M6.5 |
| `RPA_BRONZE_RETENTION_JSONL_DAYS` | int | `30` | Hot JSONL retention. Compacted to Parquet beyond this horizon. | M6.5 |
| `RPA_BRONZE_RETENTION_PARQUET_DAYS` | int | `365` | Cold Parquet retention. | M11.5 |
| `RPA_BRONZE_RETENTION_HAR_DAYS` | int | `90` | HAR network log retention. | M6.5 |
| `RPA_BRONZE_RETENTION_TRACE_DAYS` | int | `90` | Playwright trace retention. | M6.5 |
| `RPA_BRONZE_RETENTION_FAILURE_DAYS` | int | `30` | Failure screenshot/DOM retention. | M6.5 |
| `RPA_BRONZE_RETENTION_LLM_DAYS` | int | `365` | LLM call audit blob retention. | M9 |
| `RPA_GOLD_COLD_ROOT` | path | `data/gold/cold` | DuckDB-on-Parquet cold gold root. | M11.5 |

## Browser

| Var | Type | Default | Description | Owner |
|---|---|---|---|---|
| `RPA_DEFAULT_BROWSER` | `chromium` | `chromium` | Browser engine. Currently chromium-only. | M3 |
| `RPA_DEFAULT_HEADLESS` | bool | `false` | Default headless mode for `rpa record` / `rpa replay`. | M3 |

## Classifier

| Var | Type | Default | Description | Owner |
|---|---|---|---|---|
| `RPA_CLASSIFIER_CONFIDENCE_THRESHOLD` | float | `0.7` | Below this, the hybrid classifier escalates from heuristic to LLM. | M9 |
| `RPA_LLM_MODEL` | str | `claude-sonnet-4-6` | Anthropic model name. | M9 |
| `RPA_LLM_MAX_CONCURRENCY` | int | `5` | `asyncio.Semaphore` cap per `LLMClassifier` instance. Total = `worker_count × this`. | M9 |
| `RPA_LLM_CACHE_TTL_S` | int | `86400` | Response cache TTL (seconds). | M9 |
| `RPA_LLM_DAILY_BUDGET_USD` | float | `5.0` | Per-day USD cap. Raises `LLMBudgetExceeded` when hit. | M9 |
| `RPA_LLM_REQUEST_TIMEOUT_S` | float | `60.0` | Per-call timeout. | M9 |

## Recovery

| Var | Type | Default | Description | Owner |
|---|---|---|---|---|
| `RPA_RECOVERY_MAX_DEPTH` | int | `1` | Recursion cap so a recovered action can't trigger another recovery if it also fails. | M10 |
| `RPA_RECOVERY_STRATEGY_TIMEOUT_S` | float | `10.0` | Per-strategy timeout. | M10 |
| `RPA_RECOVERY_LLM_TIMEOUT_S` | float | `30.0` | `llm_reselect` strategy timeout. | M10 |

## Confirmation

| Var | Type | Default | Description | Owner |
|---|---|---|---|---|
| `RPA_CONFIRMATION_DEFAULT_FILTER` | str | `below_threshold` | Default filter axis when none specified on the CLI. | M11 |
| `RPA_CONFIRMATION_DEFAULT_MODE` | str | `per_action` | Default ask-mode. | M11 |
| `RPA_CONFIRMATION_DEFAULT_RENDERER` | str | `compact` | Default visual renderer. | M11 |
| `RPA_CONFIRMATION_AUDIT_BRONZE` | bool | `true` | Write the operator's confirmation decisions to bronze. | M11 |

## Workers

| Var | Type | Default | Description | Owner |
|---|---|---|---|---|
| `RPA_WORKER_CONCURRENCY` | int | `5` | Default `max_jobs` per ARQ worker. | M11.5 |
| `RPA_WORKER_REPLAY_MAX_JOBS` | int | `2` | `replay_queue` cap. Browser launches are expensive; keep low. | M11.5 |
| `RPA_WORKER_MEDALLION_MAX_JOBS` | int | `10` | `medallion_queue` cap. IO-bound; can run wide. | M11.5 |
| `RPA_WORKER_SHUTDOWN_TIMEOUT` | int | `60` | Seconds workers spend draining in-flight jobs on SIGTERM. | M11.5 |
| `RPA_WORKER_KEEP_RESULT` | int | `3600` | Seconds ARQ retains job results in Redis. | M11.5 |
| `RPA_WORKER_REPLAY_JOB_TIMEOUT` | int | `1800` | Hard ceiling on a single replay (30 min). | M11.5 |

## API control plane

| Var | Type | Default | Description | Owner |
|---|---|---|---|---|
| `RPA_REDIS_URL` | str | `redis://localhost:6379/0` | Redis used by ARQ + WebSocket pub/sub + LLM cache. | M11.5 / M12 |
| `RPA_QUEUE_BACKEND` | `in_process` \| `arq` | `in_process` | Selects the `QueuePool` impl. Production sets `arq`. See [ADR-0002](../.claude/plans/adr/0002-protocol-seam-for-queue-pool.md). | M12 |
| `RPA_MAX_QUEUE_DEPTH` | int | `100` | FastAPI returns HTTP 429 when `pool.queue_size() > this`. | M12 |
| `RPA_RATE_LIMIT_PER_MINUTE` | int | `60` | Per-IP rate limit. | M12 |
| `RPA_WS_HEARTBEAT_S` | float | `30.0` | WebSocket keep-alive interval. | M12 |
| `RPA_WS_EVENT_BUFFER_SIZE` | int | `1000` | Per-client buffered events on resume. | M12 |
| `RPA_API_EVENT_DEDUP_WINDOW` | int | `64` | Resume-token dedup window for WebSocket reconnects. | M12 |

## Secrets

| Var | Type | Default | Description | Owner |
|---|---|---|---|---|
| `RPA_ANTHROPIC_API_KEY` | SecretStr | unset | Anthropic API key. Stored as `pydantic.SecretStr`; never logged. Required for the LLM tier. | M9 |
| `ANTHROPIC_API_KEY` | secret | unset | Fallback the Anthropic SDK reads directly when `RPA_ANTHROPIC_API_KEY` is unset. Use one or the other; not both. | M9 |
| `CODECOV_TOKEN` | secret | unset | Optional CI coverage upload token. Used only by `.github/workflows/`. | M13 |
