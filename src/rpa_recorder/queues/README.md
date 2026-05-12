# queues

`QueuePool` Protocol + two implementations — the seam between the FastAPI
control plane and the worker layer. See
[ADR-0002](../../../.claude/plans/adr/0002-protocol-seam-for-queue-pool.md)
for the rationale and [ADR-0003](../../../.claude/plans/adr/0003-arq-over-celery-for-workers.md)
for the choice of ARQ as the production backend.

## Layout

```
queues/
├── __init__.py
├── protocol.py         # QueuePool Protocol + EnqueueResult dataclass
├── in_process.py       # InProcessQueuePool — asyncio.Task backend (tests, demos)
├── arq.py              # ArqQueuePool — ARQ + Redis backend (production default)
├── replay_handler.py   # the replay_run job body, shared between backends
└── events.py           # publish_progress(redis, run_id, event) — WebSocket pub/sub
```

## Conventions

- **The Protocol is intentionally minimal.** `enqueue_job` and
  `queue_size` are the only methods FastAPI uses. Backend-specific
  features (ARQ retry policy, in-process synchronous run) stay inside
  the impl.
- **`Config.queue_backend` selects at startup.** Default is `arq`. Tests
  and demos can set `arq` → `in_process` without touching API code.
- **Both backends publish progress through the same helper.**
  `events.publish_progress(...)` writes to a Redis-shaped channel
  (`run:{run_id}`) so the WebSocket bridge in
  [`api/streaming/manager.py`](../api/streaming/manager.py) is identical
  regardless of backend. In-process tests use `fakeredis` to satisfy
  this.
- **`queue_size` semantics differ slightly.** In-process returns
  `active + pending` for the queue; ARQ returns the true Redis ZSET
  depth. Both feed the FastAPI 429 backpressure threshold
  (`Config.max_queue_depth`) and both are good-enough saturation signals.
  Documented in `protocol.py`.

## Adding a backend

1. Add `queues/<name>.py` implementing the `QueuePool` Protocol.
2. Wire selection in [`config.py`](../config.py) — extend the
   `queue_backend` literal type and the factory in
   [`api/dependencies/queue.py`](../api/dependencies/queue.py).
3. Reuse `replay_handler.py` for the replay job body — backends differ
   in *how* jobs are scheduled, not in *what* they run.
4. Add a test under `tests/test_queues_<name>.py` covering enqueue +
   progress publish.

## See also

- [ADR-0002](../../../.claude/plans/adr/0002-protocol-seam-for-queue-pool.md) — Protocol seam rationale.
- [ADR-0003](../../../.claude/plans/adr/0003-arq-over-celery-for-workers.md) — ARQ over Celery.
- [`api/README.md`](../api/README.md) — caller side.
- [`workers/README.md`](../workers/README.md) — what runs the jobs in production.
