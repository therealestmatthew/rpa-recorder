# Workers

ARQ + Redis worker package (M11.5). Two worker classes share one job
registry but pin different queues so heavy jobs (browser replays) and
light jobs (medallion promotion, compaction) don't starve each other.

## Running

Local dev — bring up Redis first:

```bash
docker compose up -d redis
```

Then in two terminals:

```bash
uv run arq rpa_recorder.workers.settings.ReplayWorkerSettings
uv run arq rpa_recorder.workers.settings.MedallionWorkerSettings
```

Or via the CLI shortcut (added in commit 3 of M11.5):

```bash
uv run rpa worker --queue replay      # default
uv run rpa worker --queue medallion
```

## Queue layout

| Queue | `max_jobs` | Drains |
|---|---|---|
| `replay_queue` | 2 | `replay_run` (heavyweight: each spawns a `BrowserSession`) |
| `medallion_queue` | 10 | `promote_bronze_to_silver`, `promote_silver_to_gold`, `compact_bronze_to_parquet`, `prune_old_artifacts`, `classify_recording`, `generate_run_summary` |

Why split: a single replay can take 30 minutes; queueing it behind a
flood of 5-minute medallion compactions would block FastAPI's replay
enqueues. Two worker processes consume in parallel and HTTP 429 fires
when either queue exceeds `Config.max_queue_depth`.

## Cron schedule

| Job | Cadence | What |
|---|---|---|
| `compact_bronze_to_parquet` | every 15 min | bronze JSONL → snappy Parquet |
| `promote_silver_to_gold` | every hour at :00 | hot SQLAlchemy upserts + cold DuckDB Parquet |
| `prune_old_artifacts` | daily at 03:00 UTC | retention pruning |

## Why not in-process

`ArqQueuePool` lives next to `InProcessQueuePool` and satisfies the
same Protocol. The split:

- `Config.queue_backend = "in_process"` — runs jobs inside the FastAPI
  event loop. Default for tests and small-scale dev. No worker
  processes. Browser-based jobs still work but cap CI throughput.
- `Config.queue_backend = "arq"` — FastAPI enqueues to Redis; ARQ
  worker processes drain. Production shape. Workers can be scaled
  horizontally; FastAPI process is purely orchestration.

## Idempotency contract

| Job | Idempotent? | `max_tries` |
|---|---|---|
| `replay_run` | no — partial runs leave attempt rows + bronze artifacts | 1 |
| `classify_recording` | yes | 3 |
| `generate_run_summary` | yes | 3 |
| `promote_bronze_to_silver` | yes — silver count gates inserts | 3 |
| `promote_silver_to_gold` | yes — upserts + atomic Parquet replace | 3 |
| `compact_bronze_to_parquet` | yes — Parquet artifact row gates | 3 |
| `prune_old_artifacts` | yes — `delete()` is idempotent | 3 |

## SQLite write contention

Multiple workers writing to the same SQLite DB will queue on the
single global writer lock. M11.5 sets `PRAGMA journal_mode=WAL` and
`PRAGMA busy_timeout=5000` in `init_db()` to soften this — concurrent
writers wait up to 5 s instead of raising `database is locked`. Above
~2 concurrent writers, switch to Postgres (`uv sync --extra postgres`).
