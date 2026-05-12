# api

FastAPI control plane (M12). Per-resource routers, a fixed middleware stack,
streaming via WebSocket, and a `QueuePool`-shaped seam to the worker layer
(see [ADR-0002](../../../.claude/plans/adr/0002-protocol-seam-for-queue-pool.md)).

## Layout

```
api/
├── __init__.py
├── app.py                   # build_app() factory; assembles middleware + routers + lifespan
├── lifespan.py              # startup/shutdown: open DB engine, redis pool, queue pool
├── dependencies/            # FastAPI Depends(...) wiring
│   ├── config.py            # Config singleton
│   ├── db.py                # AsyncSession per-request
│   ├── queue.py             # QueuePool (in-process or arq)
│   ├── redis.py             # redis.asyncio.Redis pool
│   └── ws_manager.py        # WebSocketManager singleton
├── middleware/              # ordered ASGI middleware (registered top-down in app.py)
│   ├── request_id.py        # X-Request-ID propagation + structlog bind
│   ├── structured_logging.py
│   ├── rate_limit.py        # per-IP token bucket
│   └── backpressure.py      # 429 when queue depth > Config.max_queue_depth
├── routers/                 # one module per resource
│   ├── health.py            # /healthz, /readyz
│   ├── recordings.py        # CRUD over recordings
│   ├── runs.py              # run results / detail
│   ├── replay.py            # POST /replay/{recording_id} → enqueue
│   ├── medallion.py         # POST /medallion/recompute
│   └── streaming.py         # WS /runs/{run_id}/stream → redis pub/sub bridge
├── schemas/                 # request/response Pydantic models
│   ├── recording.py
│   ├── run.py
│   ├── medallion.py
│   ├── events.py            # WS frame shapes
│   └── errors.py            # ProblemDetails-style errors
└── streaming/
    └── manager.py           # WebSocketManager: subscribe→bridge→fan-out
```

## Conventions

- **Routers depend on schemas, not domain models.** Schemas live in
  `schemas/`; domain types live in [`rpa_recorder.models`](../models/) and
  cross the seam through repositories or direct mapping in the router.
- **Middleware order is load-bearing.** `request_id` runs first (so every
  log line has a request id); `backpressure` runs last (so rate-limited and
  unauthenticated requests don't reserve queue depth). `app.py` registers
  them in reverse-call order per Starlette's stack semantics.
- **Replays enqueue, never run inline.** Routers go through the
  `QueuePool` Protocol — see [ADR-0002](../../../.claude/plans/adr/0002-protocol-seam-for-queue-pool.md).
- **WebSocket endpoints bridge Redis pub/sub.** The WebSocketManager
  subscribes to `run:{run_id}` channels in Redis and fans out to clients;
  workers `publish_progress(...)` on the same channel. No direct
  worker→websocket coupling.
- **Errors return the `errors.ProblemDetails` schema** with a stable
  `type` URI and `code` field. Don't leak internal exception text.

## Adding a new router

1. Create `routers/<resource>.py` with an `APIRouter(prefix="/<resource>", tags=[...])`.
2. Add the request/response models to `schemas/<resource>.py`.
3. Register the router in `app.py` via `app.include_router(...)`.
4. Add tests in `tests/test_api_<resource>.py` using `httpx.AsyncClient`
   against an `InProcessQueuePool` instance.
5. If the new endpoint enqueues work, do it through `Depends(get_queue_pool)`
   — never import a backend directly.

## See also

- [`docs/m12-fastapi-control-plane.md`](../../../docs/m12-fastapi-control-plane.md) — milestone doc.
- [ADR-0002](../../../.claude/plans/adr/0002-protocol-seam-for-queue-pool.md) — `QueuePool` rationale.
- [`workers/README.md`](../workers/README.md) — what's on the other side of the seam.
