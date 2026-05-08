# M12 — FastAPI control plane (modular routers + middleware)

**Status:** done (Protocol-seam variant — see *Protocol seam* below)

**Source:** [.claude/plans/bootstrap.md](../.claude/plans/bootstrap.md) §API Specification; [.claude/plans/data-capture.md](../.claude/plans/data-capture.md) §7 (event taxonomy); [build-plan.md](build-plan.md) §Concurrency conventions; [m11.5-workers-and-medallion-promotion.md](m11.5-workers-and-medallion-promotion.md) for the worker contract this plane consumes.

## Protocol seam (M12-as-shipped)

M11.5 was still pending when M12 landed, so this milestone shipped against a `QueuePool` Protocol seam instead of a direct ARQ dependency. Routes call `pool.enqueue_job(...)` and the lifespan picks the backend by `Config.queue_backend`:

- `in_process` (default): `InProcessQueuePool` runs jobs in the FastAPI event loop with a per-queue `asyncio.Semaphore` (`replay_queue=2`, `medallion_queue=10`). Each job publishes through the same `publish_progress(redis, run_id, event)` helper an ARQ worker would, so the WebSocket layer reads from Redis without caring which backend produced the events.
- `arq`: raises `RuntimeError("queue_backend=arq requires M11.5...")` until M11.5 ships `ArqQueuePool` next door.

The seam lives in `src/rpa_recorder/queues/` (`protocol.py`, `events.py`, `in_process.py`, `replay_handler.py`). M11.5 will add `queues/arq.py` (a thin `ArqQueuePool` adapter over `arq.connections.ArqRedis`) and re-import `replay_handler.run_replay` into `workers/jobs/replay.py`.

`POST /medallion/recompute` and `/medallion/compact` accept the request and return `202` with `status="deferred"` while `queue_backend=in_process`. They enqueue the real `promote_silver_to_gold` / `compact_bronze_to_parquet` jobs once M11.5 sets `queue_backend=arq`. The contract is stable across backends.

### Known constraints

- **Local dev still requires Redis** even with `queue_backend=in_process`, because `WebSocketManager` and `publish_progress` use Redis pub/sub regardless. `docker run --rm -p 6379:6379 redis:7-alpine` before `rpa serve`.
- `arq` is **not** added to `pyproject.toml`. M11.5 adds it. The `redis>=5` and `httpx>=0.27` deps land in M12; tests use `fakeredis[lua]`, `asgi-lifespan`, and `httpx-ws`.

## Goal

A FastAPI app that exposes recordings + runs + medallion operations over HTTP, streams live executor events over WebSockets, and acts as a thin orchestration layer above M11.5's ARQ workers — never doing replay work in-process. Modular layout with per-resource routers, pluggable middleware, dependency-injection factories, a dedicated WebSocket fan-out manager, and a lifespan-managed dependency stack.

The architecture means: adding `POST /recordings/{id}/share` = a new file under `routers/`, one import in `app.py`, dedicated tests. Adding rate-limit middleware = a new file under `middleware/`, one append to the middleware stack. The worker / medallion seam is owned cleanly: HTTP enqueues into ARQ, WebSocket bridges Redis pub/sub channels to clients, FastAPI never blocks on replay/classification/promotion.

## Files

### Create

- `src/rpa_recorder/api/__init__.py` — re-exports `app: FastAPI` (preserves `pyproject.toml`'s `rpa serve` → `uvicorn rpa_recorder.api:app`)
- `src/rpa_recorder/api/app.py` — `FastAPI(...)` construction, middleware stack registration, router includes, lifespan wiring
- `src/rpa_recorder/api/lifespan.py` — `@asynccontextmanager` for startup (engine, ARQ pool, Redis client, WebSocketManager) and shutdown (reverse order, drain WS, close pool)
- `src/rpa_recorder/api/dependencies/__init__.py`
- `src/rpa_recorder/api/dependencies/db.py` — `get_session()` yields an `AsyncSession`
- `src/rpa_recorder/api/dependencies/arq.py` — `get_arq_pool()` yields the process-singleton `ArqRedis`
- `src/rpa_recorder/api/dependencies/redis.py` — `get_redis()` yields the shared `redis.asyncio.Redis`
- `src/rpa_recorder/api/dependencies/config.py` — `get_config()`
- `src/rpa_recorder/api/dependencies/ws_manager.py` — `get_ws_manager()` returns the process-singleton `WebSocketManager`
- `src/rpa_recorder/api/routers/__init__.py` — explicit registry: `all_routers()` returns the list `app.py` includes
- `src/rpa_recorder/api/routers/health.py` — `GET /healthz`, `GET /readyz`
- `src/rpa_recorder/api/routers/recordings.py` — `GET /recordings`, `GET /recordings/{id}`
- `src/rpa_recorder/api/routers/runs.py` — `GET /runs`, `GET /runs/{id}`, `POST /runs/{id}/cancel`
- `src/rpa_recorder/api/routers/replay.py` — `POST /recordings/{id}/replay`
- `src/rpa_recorder/api/routers/medallion.py` — `POST /medallion/recompute`, `GET /medallion/status`, `POST /medallion/compact`
- `src/rpa_recorder/api/routers/streaming.py` — WebSocket `/runs/{id}/stream`
- `src/rpa_recorder/api/middleware/__init__.py` — explicit registry: `default_middleware_stack()` returns ordered list
- `src/rpa_recorder/api/middleware/request_id.py` — `X-Request-ID` header in/out
- `src/rpa_recorder/api/middleware/structured_logging.py` — `structlog.contextvars.bind_contextvars(request_id, method, path)`
- `src/rpa_recorder/api/middleware/rate_limit.py` — Redis-backed token bucket per IP
- `src/rpa_recorder/api/middleware/backpressure.py` — 429 when `pool.queue_size() > Config.max_queue_depth`
- `src/rpa_recorder/api/streaming/__init__.py`
- `src/rpa_recorder/api/streaming/manager.py` — `WebSocketManager`: multiplex Redis pub/sub `run:{id}` to multiple WebSocket subscribers, backfill from `events:{id}` Redis list, heartbeat ping
- `src/rpa_recorder/api/schemas/__init__.py`
- `src/rpa_recorder/api/schemas/recording.py` — `RecordingSummary`, `RecordingDetail`
- `src/rpa_recorder/api/schemas/run.py` — `RunStatus`, `RunDetail`, `ReplayRequest`, `ReplayResponse`, `CancelResponse`
- `src/rpa_recorder/api/schemas/medallion.py` — `MedallionStatus`, `RecomputeRequest`, `RecomputeResponse`
- `src/rpa_recorder/api/schemas/events.py` — WebSocket event taxonomy Pydantic models
- `src/rpa_recorder/api/schemas/errors.py` — `ErrorEnvelope`
- `tests/test_api_app.py`
- `tests/test_api_lifespan.py`
- `tests/test_api_dependencies.py`
- `tests/test_api_routers_health.py`
- `tests/test_api_routers_recordings.py`
- `tests/test_api_routers_runs.py`
- `tests/test_api_routers_replay.py`
- `tests/test_api_routers_medallion.py`
- `tests/test_api_routers_streaming.py`
- `tests/test_api_middleware_request_id.py`
- `tests/test_api_middleware_structured_logging.py`
- `tests/test_api_middleware_rate_limit.py`
- `tests/test_api_middleware_backpressure.py`
- `tests/test_api_streaming_manager.py`
- `tests/test_api_e2e.py` — full record-then-replay flow via HTTP + WebSocket (`@pytest.mark.integration`, requires Redis)

### Modify

- `src/rpa_recorder/cli/commands/serve.py` — already invokes `uvicorn.run("rpa_recorder.api:app", ...)`; verify the import path resolves to the new package
- `src/rpa_recorder/browser/executor.py` — `Executor.__init__` adds `event_emitter: Callable[[str, dict[str, Any]], Awaitable[None] | None] | None = None` (two-arg `(event_type, payload)` shape, matching `RecoveryEngine`'s existing emitter so they compose without an adapter). The in-process replay handler (and M11.5's worker) wires this to a closure that calls `publish_progress(redis, run_id, {"type": event_type, **payload})`. Events emitted by the executor: `run_started`, `action_started`, `action_succeeded`, `action_failed`, `run_finished`. Recovery's existing `recovery_started|succeeded|failed` events flow through unchanged when the same emitter is also wired into `RecoveryEngine`.
- `src/rpa_recorder/config.py` — add `max_queue_depth: int = 100`, `rate_limit_per_minute: int = 60`, `ws_heartbeat_s: float = 30.0`, `ws_event_buffer_size: int = 1000`

## Public API

### `api/app.py`

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from .lifespan import lifespan
from .middleware import default_middleware_stack
from .routers import all_routers


def create_app() -> FastAPI:
    app = FastAPI(
        title="rpa-recorder",
        version="0.1.0",
        lifespan=lifespan,
    )
    for mw_cls, kwargs in default_middleware_stack():
        app.add_middleware(mw_cls, **kwargs)
    for router in all_routers():
        app.include_router(router)
    return app


app = create_app()
```

### `api/lifespan.py`

```python
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    config = Config()
    engine = create_async_engine(config.database_url, ...)
    redis = aioredis.from_url(config.redis_url, max_connections=20)
    arq_pool = await create_pool(RedisSettings.from_dsn(config.redis_url))
    ws_manager = WebSocketManager(redis=redis, buffer_size=config.ws_event_buffer_size)
    app.state.config = config
    app.state.engine = engine
    app.state.redis = redis
    app.state.arq_pool = arq_pool
    app.state.ws_manager = ws_manager
    try:
        yield
    finally:
        # reverse-order shutdown
        await ws_manager.close()
        await arq_pool.close()
        await redis.aclose()
        await engine.dispose()
```

### `api/dependencies/*.py`

Each is a thin FastAPI dependency that pulls from `app.state`:

```python
async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    SessionLocal = async_sessionmaker(request.app.state.engine, expire_on_commit=False)
    async with SessionLocal() as session:
        yield session


def get_arq_pool(request: Request) -> ArqRedis:
    return request.app.state.arq_pool


def get_redis(request: Request) -> Redis:
    return request.app.state.redis


def get_ws_manager(request: Request) -> WebSocketManager:
    return request.app.state.ws_manager


def get_config(request: Request) -> Config:
    return request.app.state.config
```

### Per-router shape

Each router file declares one `APIRouter` and registers its handlers. Example (`routers/replay.py`):

```python
router = APIRouter(prefix="/recordings", tags=["replay"])


@router.post("/{rid}/replay", response_model=ReplayResponse)
async def start_replay(
    rid: UUID,
    body: ReplayRequest,
    pool: ArqRedis = Depends(get_arq_pool),
    config: Config = Depends(get_config),
) -> ReplayResponse:
    if await pool.queue_size("replay_queue") > config.max_queue_depth:
        raise HTTPException(429, "replay queue saturated")
    run_id = uuid4()
    await pool.enqueue_job(
        "replay_run",
        run_id=str(run_id),
        recording_id=str(rid),
        params=body.parameters,
        _queue_name="replay_queue",
    )
    return ReplayResponse(run_id=run_id, status="queued")
```

This shape is the contract for every router: `APIRouter` with explicit `prefix` + `tags`, dependency-injected ARQ pool / session / redis / config, schemas in / schemas out, no business logic — that lives in M11.5 jobs and the medallion package.

### Router registry

```python
# routers/__init__.py
from .health import router as health_router
from .recordings import router as recordings_router
from .runs import router as runs_router
from .replay import router as replay_router
from .medallion import router as medallion_router
from .streaming import router as streaming_router


def all_routers() -> list[APIRouter]:
    return [
        health_router,
        recordings_router,
        runs_router,
        replay_router,
        medallion_router,
        streaming_router,
    ]
```

To add a new resource: new file + one import + append to the list.

### Middleware registry

```python
# middleware/__init__.py
from .request_id import RequestIdMiddleware
from .structured_logging import StructuredLoggingMiddleware
from .rate_limit import RateLimitMiddleware
from .backpressure import BackpressureMiddleware


def default_middleware_stack() -> list[tuple[type[BaseHTTPMiddleware], dict[str, Any]]]:
    """Order matters. Outermost first.

      RequestId    (assigns X-Request-ID, before logging needs it)
      Logging      (binds structlog contextvars)
      RateLimit    (per-IP token bucket; 429 before doing work)
      Backpressure (only on enqueueing routes; 429 if queue saturated)
    """
    return [
        (RequestIdMiddleware, {}),
        (StructuredLoggingMiddleware, {}),
        (RateLimitMiddleware, {"per_minute": Config().rate_limit_per_minute}),
        (BackpressureMiddleware, {"protected_paths": ("/recordings/{rid}/replay",)}),
    ]
```

### `api/streaming/manager.py`

```python
class WebSocketManager:
    """Multiplex Redis pub/sub channels to multiple WebSocket subscribers
    per run. Handles:
      - per-run pub/sub subscription (one Redis subscriber per active run)
      - per-subscriber send queue with bounded buffer
      - heartbeat ping every Config.ws_heartbeat_s seconds
      - backfill from Redis list `events:{run_id}` for late joiners
      - graceful disconnect: unsubscribe pub/sub when last subscriber leaves
    """

    def __init__(self, *, redis: Redis, buffer_size: int = 1000) -> None: ...

    async def subscribe(self, run_id: UUID, ws: WebSocket) -> None:
        """Run for the lifetime of one WebSocket connection.

        On entry: send backfill events (LRANGE events:{run_id}), then
        subscribe to pub/sub channel run:{run_id}, forward each message
        to ws.send_json. On disconnect or cancellation: unsubscribe and
        decrement subscriber count for that run; if count hits 0, close
        the pub/sub subscription."""

    async def close(self) -> None:
        """Drain all subscribers cleanly on app shutdown."""
```

## Behavior

### Endpoint catalog

| Verb + Path | Purpose | Body in | Body out | Notes |
|---|---|---|---|---|
| `GET /healthz` | liveness | — | `{ok: true}` | no DB / Redis access; for k8s |
| `GET /readyz` | readiness | — | `{db: ok\|fail, redis: ok\|fail, arq: ok\|fail}` | pings each dependency |
| `GET /recordings` | list | — | `list[RecordingSummary]` | paginated via `?limit&offset` |
| `GET /recordings/{rid}` | detail | — | `RecordingDetail` | redacts sensitive payloads |
| `GET /runs` | list | — | `list[RunStatus]` | filter by `?recording_id&status` |
| `GET /runs/{rid}` | detail | — | `RunDetail` | reads silver |
| `POST /runs/{rid}/cancel` | cancel | — | `CancelResponse` | sets a Redis cancellation flag the worker checks |
| `POST /recordings/{rid}/replay` | enqueue replay | `ReplayRequest{parameters}` | `ReplayResponse{run_id, status}` | 429 if queue saturated |
| `POST /medallion/recompute` | trigger gold | `RecomputeRequest{recording_id?}` | `RecomputeResponse{job_id}` | enqueues `promote_silver_to_gold` on `medallion_queue` |
| `POST /medallion/compact` | trigger compaction | — | `RecomputeResponse{job_id}` | enqueues `compact_bronze_to_parquet` |
| `GET /medallion/status` | layer freshness | — | `MedallionStatus` | reads `BronzeArtifactRow` counts + `gold_*_at` columns |
| `WebSocket /runs/{rid}/stream` | live events | — | event stream | bridges Redis pub/sub `run:{rid}`; backfills from `events:{rid}` list |

### Replay flow (the one that exercises everything)

1. Client `POST /recordings/{rid}/replay` with `{parameters: {email: "..."}}`.
2. `BackpressureMiddleware` checks `await pool.queue_size("replay_queue")`. If above `Config.max_queue_depth`, returns 429 with `Retry-After: 30`.
3. Handler validates the recording exists (`get_session()` + `RecordingRepository.get_recording`).
4. Handler generates `run_id = uuid4()`, calls `pool.enqueue_job("replay_run", run_id=str(run_id), recording_id=str(rid), params=body.parameters, _queue_name="replay_queue")`. Returns `{run_id, status: "queued"}` immediately.
5. ARQ worker on `replay_queue` (M11.5) picks up the job, opens a `BrowserSession`, runs the `Executor` with `event_emitter=publish_progress_factory(redis, run_id)`. Each per-action event is published to `run:{run_id}` pub/sub *and* `LPUSH events:{run_id}` Redis list (capped at 1000 entries via `LTRIM`).
6. Client opens `ws://.../runs/{run_id}/stream`. The handler calls `ws_manager.subscribe(run_id, ws)`:
   - Backfill: `LRANGE events:{run_id} 0 -1` → reverse → forward each via `ws.send_json` so the client sees history first.
   - Subscribe: `pubsub = redis.pubsub(); await pubsub.subscribe(f"run:{run_id}")`. Forward each message to `ws.send_json` until disconnect.
   - Heartbeat: every 30 s, send `{"type": "heartbeat", "ts": ...}`.
7. On run completion, the worker publishes `run_finished` and persists `RunResult`. Client receives the event and disconnects (or stays for the next replay).
8. M11.5's `prune_old_artifacts` cron eventually trims the `events:{run_id}` list.

### Cancellation flow

1. Client `POST /runs/{rid}/cancel` (where `rid` is the run id).
2. Handler writes `await redis.set(f"cancel:{rid}", "1", ex=3600)`.
3. The `replay_run` worker checks this flag at every action boundary (per M11.5's *Cancellation propagation* pitfall). On hit: aborts the action loop, persists `RunResult.status=CANCELLED`, publishes `run_cancelled`.
4. WebSocket subscribers receive the event and the manager closes the channel after a short drain.

### Backfill semantics

WebSocket subscribers connecting *after* a run started would otherwise miss early events (Redis pub/sub doesn't buffer). The mitigation:

- Worker writes every event to **both** `PUBLISH run:{id}` and `LPUSH events:{id}`. The list is capped at `Config.ws_event_buffer_size` (default 1000) via `LTRIM`.
- WebSocket subscribe path drains the list (`LRANGE 0 -1`, reverse) before subscribing to pub/sub. There's a small race window where an event could appear between LRANGE and SUBSCRIBE — the `WebSocketManager` deduplicates by `event_id` (UUID per event from the worker) on the client-facing send.

### Heartbeat semantics

`WebSocketManager` sends a `{"type": "heartbeat", "ts": ...}` frame every `Config.ws_heartbeat_s` seconds (default 30 s). Clients use this to detect a stale connection. If a `ws.send_json` raises (broken pipe), the manager catches and removes the subscriber, decrementing the run's reference count.

### Adding a new endpoint (worked example: `POST /recordings/{rid}/share`)

To export a recording as a shareable link / signed URL:

1. Create `src/rpa_recorder/api/routers/share.py`:
   ```python
   router = APIRouter(prefix="/recordings", tags=["share"])

   @router.post("/{rid}/share", response_model=ShareResponse)
   async def share_recording(
       rid: UUID,
       session: AsyncSession = Depends(get_session),
       config: Config = Depends(get_config),
   ) -> ShareResponse:
       ...
   ```
2. Add `from .share import router as share_router` and append to `all_routers()`.
3. Add `tests/test_api_routers_share.py`.

No edits to `app.py`, lifespan, middleware, or other routers. The dependency stack is reused.

### Adding a new middleware (worked example: `AuthMiddleware`)

For future API-key auth:

1. Create `src/rpa_recorder/api/middleware/auth.py` with `class AuthMiddleware(BaseHTTPMiddleware)`. `dispatch(request, call_next)` checks `Authorization: Bearer <key>` header against `Config.api_keys`; raises 401 on miss.
2. Append to `default_middleware_stack()` *between* `StructuredLoggingMiddleware` and `RateLimitMiddleware` (so unauthorized requests still get a request ID for tracing but bypass rate-limit token spend).
3. Add `tests/test_api_middleware_auth.py`.

The order matters and is documented in the middleware module's docstring.

## Concurrency

Inherits the cross-cutting rules from [build-plan.md](build-plan.md) §Concurrency conventions. M12-specific applications:

- **Process-singleton dependencies.** `engine`, `arq_pool`, `redis`, `ws_manager` all live on `app.state` and are created once in `lifespan`. Per-request `get_session()` yields a new `AsyncSession` from the engine's pool; everything else is shared.
- **No replay work in-process.** `POST /replay` is a 50 ms enqueue, never minutes of browser driving. The FastAPI worker process stays responsive; replays burn CPU/memory in M11.5's worker processes.
- **WebSocket subscriber bounded buffer.** `WebSocketManager` keeps a per-subscriber `asyncio.Queue(maxsize=ws_event_buffer_size)` between the pub/sub reader and `ws.send_json`. If the client is slow, the queue fills, the manager drops oldest events with a structlog warning, and the connection survives. Don't unbound the queue — slow clients would balloon worker memory.
- **Pub/sub subscription ref-count.** Multiple WebSocket clients on the same `/runs/{id}/stream` share one `redis.pubsub()` subscription. The manager increments on subscribe, decrements on disconnect; only when count reaches 0 does it `await pubsub.unsubscribe(...)`. Avoids fan-out latency multiplication.
- **Cancellation propagation.** When a WebSocket disconnects (`WebSocketDisconnect` exception), the manager catches it inside the per-subscriber task, removes the subscriber, and exits cleanly. The pub/sub task is unaffected for other subscribers.
- **Backpressure.** `BackpressureMiddleware` checks `pool.queue_size("replay_queue")` only for the protected paths (default: `POST /recordings/{rid}/replay`). Read-only paths and medallion-queue enqueues are not throttled here.
- **Rate limit.** `RateLimitMiddleware` uses a Redis `INCR` + `EXPIRE` token bucket per IP. The check is one round-trip; cheap. On exceed: 429 with `Retry-After`.
- **Reverse-order shutdown.** `lifespan`'s `finally` closes `ws_manager` first (drains active WebSockets), then `arq_pool`, then `redis`, then `engine`. Out-of-order shutdown causes "RuntimeError: Event loop is closed" warnings.
- **No `asyncio.create_task` in handlers.** All long-running work goes to ARQ. Avoid the pre-M11.5 spec's `app.state.runs[run_id] = task` pattern entirely — orphaned tasks silently die when the worker process restarts. ARQ persists jobs to Redis; restarts pick up where they left off.
- **No global `Semaphore`s in M12.** Concurrency caps live in M9 (LLM) and M11.5 (browsers, queue concurrency). FastAPI just passes through.

## Medallion / worker integration

| Layer | Effect |
|---|---|
| Bronze | the FastAPI process never writes bronze directly; workers (M6.5 / M11.5) own bronze writes |
| Silver | read-only via `RecordingRepository`, `RunResultRepository` (M5) for `GET` endpoints; `POST /runs/{rid}/cancel` writes `RunResult.status=CANCELLED` (queued via worker) |
| Cold gold | `GET /medallion/status` reads `BronzeArtifactRow` counts + the gold tables' `computed_at` columns to surface freshness; doesn't run DuckDB queries directly (those are M11.5) |
| Worker | every long-running operation enqueues into ARQ: `replay_run` (replay queue), `promote_silver_to_gold` (medallion queue), `compact_bronze_to_parquet` (medallion queue), `classify_recording` (medallion queue, future endpoint) |
| Streaming | WebSocket bridges `run:{id}` Redis pub/sub channels published by M11.5's `replay_run` (and `recovery_*` events from M10) |

## Integration points

| Touch | File | How |
|---|---|---|
| M2 → M12 | [src/rpa_recorder/models/](../src/rpa_recorder/models/) | request/response schemas in `api/schemas/` mirror Pydantic models with redaction context applied |
| M5 → M12 | [src/rpa_recorder/storage/repositories.py](../src/rpa_recorder/storage/repositories.py) | every `GET` handler depends on the repos via `get_session()` |
| M6 → M12 | [src/rpa_recorder/browser/executor.py](../src/rpa_recorder/browser/executor.py) | `Executor.__init__` gains `event_emitter` parameter; M11.5 wires it to `publish_progress(redis, run_id)`; M12 doesn't call `Executor` directly but defines the event taxonomy |
| M6.5 → M12 | bronze layer | `GET /medallion/status` joins `bronze_artifacts` rows |
| M9 → M12 | future `POST /recordings/{rid}/classify` enqueues `classify_recording` (medallion queue) — placeholder router file optional in M12 or deferred |
| M10 → M12 | recovery events (`recovery_started`, `recovery_succeeded`, `recovery_failed`) flow through the same WebSocket as replay events |
| M11 → M12 | `POST /recordings/{rid}/confirmations` (web equivalent of CLI `rpa confirm`) — reuses M11's `ConfirmationRunner` with a different renderer; left as a future router unless explicitly in scope |
| M11.5 → M12 | the entire enqueue / pub-sub / queue_size / cron-aware status surface |
| M12 → M13 | CI brings up `redis:7-alpine` + the `medallion_queue` worker so the `@pytest.mark.integration` API tests can run end-to-end |

## Models / DB rows used

- **Reads:** `RecordingRow`, `RecordedActionRow`, `RunResultRow`, `ActionExecutionRow`, `ExecutionAttemptRow`, `BronzeArtifactRow`, `GoldRecordingMetricsRow`, `GoldRunDashboardRow` (M5 + M6.5 + M11.5).
- **Writes:** none direct — all writes go through worker jobs.
- **Indirect writes via worker enqueue:** `RunResultRow` (created by `replay_run`), `Gold*Row` (recomputed by `promote_silver_to_gold`).

## Tests

`tests/test_api_app.py`:
- `test_create_app_returns_fastapi_with_routers` — assert all default routers present in `app.routes`.
- `test_create_app_registers_middleware_in_order` — assert middleware classes match `default_middleware_stack()` order.

`tests/test_api_lifespan.py`:
- `test_lifespan_initializes_app_state(test_client)` — startup populates `app.state.engine` / `arq_pool` / `redis` / `ws_manager`.
- `test_lifespan_tears_down_in_reverse_order(monkeypatch)` — patch each `close`/`dispose` to record call order; assert ws_manager → arq_pool → redis → engine.
- `test_lifespan_propagates_exception_during_startup(monkeypatch)` — make engine creation raise; assert app fails to start cleanly without leaking other resources.

`tests/test_api_dependencies.py`:
- `test_get_session_yields_session_per_request(async_client)` — two requests get different session instances.
- `test_get_arq_pool_is_singleton(async_client)` — same pool instance across two requests.

`tests/test_api_routers_health.py`:
- `test_healthz_returns_ok(async_client)` — 200 + `{ok: true}`.
- `test_readyz_pings_dependencies(async_client, mock_redis_failing)` — Redis down → `redis: fail` in body, 503 status.

`tests/test_api_routers_recordings.py`:
- `test_list_recordings_returns_summaries(seeded_db, async_client)`.
- `test_get_recording_returns_detail_with_redaction(seeded_db, async_client)` — sensitive payloads → `***`.
- `test_get_recording_404_for_unknown_id(async_client)`.
- `test_list_recordings_supports_pagination(seeded_db_50, async_client)`.

`tests/test_api_routers_runs.py`:
- `test_list_runs_filters_by_recording_id`.
- `test_get_run_includes_attempts_and_recovery`.
- `test_cancel_run_writes_redis_flag(async_client, mock_redis)` — assert `cancel:{run_id}` set with TTL.

`tests/test_api_routers_replay.py`:
- `test_replay_enqueues_job_and_returns_run_id(async_client, mock_arq_pool)` — assert `enqueue_job` called with `replay_run` + run_id; response has matching run_id.
- `test_replay_returns_429_when_queue_saturated(async_client, mock_arq_pool)` — `queue_size` returns 200 (above default 100); response is 429 with `Retry-After`.
- `test_replay_404_for_unknown_recording(async_client)`.

`tests/test_api_routers_medallion.py`:
- `test_recompute_enqueues_gold_promotion_job(async_client, mock_arq_pool)`.
- `test_compact_enqueues_compaction_job(async_client, mock_arq_pool)`.
- `test_status_returns_layer_freshness(seeded_db, async_client)`.

`tests/test_api_routers_streaming.py` (uses `httpx.AsyncClient` + ASGI WebSocket testing):
- `test_subscribe_forwards_pubsub_messages(async_ws, mock_redis_pubsub)` — publish two events to `run:{id}`; client receives them in order.
- `test_subscribe_backfills_from_event_list(async_ws, seeded_redis_list)` — five events in `events:{id}` list; client receives them on connect, then subscribes for new ones.
- `test_subscribe_sends_heartbeat(async_ws, monkeypatch_clock)` — advance time by 30 s; client receives `{"type": "heartbeat"}`.
- `test_subscribe_handles_disconnect_cleanly(async_ws)` — client disconnects mid-stream; ws_manager decrements ref count; no orphan task.

`tests/test_api_middleware_request_id.py`:
- `test_request_id_added_to_response_when_missing(async_client)`.
- `test_request_id_preserved_when_provided(async_client)` — client sends `X-Request-ID: foo`; response echoes `foo`.

`tests/test_api_middleware_structured_logging.py`:
- `test_structlog_context_bound_per_request(caplog, async_client)` — capture structlog output; assert `request_id`, `method`, `path` keys present.

`tests/test_api_middleware_rate_limit.py`:
- `test_rate_limit_allows_under_threshold(mock_redis, async_client)`.
- `test_rate_limit_returns_429_when_exceeded(mock_redis_at_limit, async_client)` — assert `Retry-After` header.

`tests/test_api_middleware_backpressure.py`:
- `test_backpressure_only_protects_replay_path(mock_arq_pool_full, async_client)` — `GET /recordings` returns 200 even with full queue; `POST /replay` returns 429.

`tests/test_api_streaming_manager.py`:
- `test_manager_multiplexes_subscribers_per_run(mock_redis_pubsub)` — two subscribers on same run → one underlying pub/sub subscription.
- `test_manager_unsubscribes_when_last_subscriber_leaves(mock_redis_pubsub)` — both disconnect; `pubsub.unsubscribe` called.
- `test_manager_drops_oldest_when_subscriber_buffer_full(monkeypatch)` — monkeypatch slow `ws.send_json`; assert oldest events dropped with structlog warnings.
- `test_manager_close_drains_active_subscribers(mock_redis_pubsub)`.

`tests/test_api_e2e.py` (`@pytest.mark.integration`, requires Redis service):
- `test_full_replay_flow(redis_container, fixture_recording, async_client)` — `POST /replay` → poll `GET /runs/{id}` until status complete; assert run persisted; bronze artifacts exist.
- `test_websocket_streams_during_replay(redis_container, fixture_recording, async_ws_client)` — `POST /replay` then connect to WS; assert event sequence per data-capture.md §7 taxonomy.

Coverage target: **≥80%** on the `api/` package (some integration paths excluded).

## Known pitfalls

- **`TestClient` is sync; `httpx.AsyncClient` is async.** For routers that use `async def` handlers and async dependencies, `httpx.AsyncClient(transport=ASGITransport(app=app))` is the right tool. `TestClient` works for many cases but blocks. Test mix: `httpx.AsyncClient` for HTTP, `TestClient`'s `websocket_connect` (sync — uses an internal threadpool) or `httpx-ws` for WebSocket.
- **Lifespan vs request scope.** `app.state.*` is shared across requests; per-request scope must come from `Depends(get_session)` etc. Don't put `AsyncSession` on `app.state` — sessions are per-operation.
- **`async with SessionLocal()` in dependencies.** `get_session` uses `yield`; FastAPI invokes the generator-context-manager lifecycle automatically. Don't manually open/close — that breaks DI scoping.
- **WebSocket disconnect detection is awkward.** `await websocket.receive_*` in a separate task is the canonical way to detect client disconnect. The `WebSocketManager` runs a tiny "drain receive" task per subscriber that catches `WebSocketDisconnect` and signals shutdown. Without this, a sender blocked on `send_json` to a dead socket would hang until TCP timeout.
- **Pub/sub task lifecycle.** Each subscribed run has *one* asyncio task pulling from `pubsub.listen()` and fan-outing to per-subscriber queues. If this task dies, all subscribers stall. Wrap in `try/except` + restart-with-backoff inside `WebSocketManager`. Heartbeat doubles as a liveness check.
- **Backpressure check race.** `pool.queue_size()` and `enqueue_job` are not atomic — between the check and the enqueue, another request could fill the slot. Acceptable in practice (over-shoot by a handful of jobs, not a magnitude). Don't try to atomically check-and-enqueue with Lua scripts; not worth the complexity.
- **CORS.** Not in the default middleware stack. If the project ever serves a browser-side UI on a different origin, add `CORSMiddleware` near the top of the stack.
- **OpenAPI / docs at `/docs`.** Default FastAPI serves these; verify they don't leak sensitive Pydantic field examples (e.g., a `password` example in `RecordingDetail`). Set `Config.examples` thoughtfully or disable docs in prod (`FastAPI(docs_url=None)`).
- **Cancellation token TTL.** The Redis cancel flag has 1 h TTL. If a user cancels and a new replay reuses the same run_id (shouldn't happen — UUIDs — but defensive), the new run could see a stale cancel. UUIDs make this practically impossible; document anyway.
- **Streaming response timeouts.** Some load balancers cut idle WebSocket connections after 60 s. Heartbeat at 30 s defaults this safely; if deploying behind a stricter LB, lower `Config.ws_heartbeat_s`.
- **`asyncio.TaskGroup` not used in WebSocketManager.** Subscribers are per-connection long-lived tasks; `TaskGroup` would force their lifetime to match, which is wrong. Use bare `asyncio.create_task` with explicit lifecycle management — and document that this is one of the few places `TaskGroup` doesn't fit.
- **PEP 758 except syntax.** Python 3.14 allows parens-less `except A, B:`. Style choice.

## Commit

`feat(api): add modular FastAPI control plane with routers, middleware, WebSocket manager`

Body: implements the FastAPI app as a package (`api/__init__.py`, `app.py`, `lifespan.py`) with per-resource routers (`health`, `recordings`, `runs`, `replay`, `medallion`, `streaming`), pluggable middleware (`request_id`, `structured_logging`, `rate_limit`, `backpressure`), dependency-injection factories (`get_session`, `get_arq_pool`, `get_redis`, `get_ws_manager`, `get_config`), and a dedicated `WebSocketManager` that multiplexes Redis pub/sub channels to subscribers with backfill from a Redis list and per-subscriber bounded send buffers. Long-running work is never done in-process — `POST /replay` enqueues into M11.5's `replay_queue`, `POST /medallion/recompute` enqueues into `medallion_queue`. Backpressure middleware returns 429 when `pool.queue_size() > Config.max_queue_depth`. Cancellation via a Redis flag the worker checks at action boundaries. Adding a new endpoint = new file + one import + append to registry.

## Critical files

- `src/rpa_recorder/api/app.py` and `lifespan.py` — wiring + dependency lifecycle
- `src/rpa_recorder/api/routers/__init__.py` — registry; routers per resource
- `src/rpa_recorder/api/middleware/__init__.py` — registry; middleware in order
- `src/rpa_recorder/api/streaming/manager.py` — WebSocket fan-out
- `src/rpa_recorder/api/dependencies/{db,arq,redis,ws_manager,config}.py` — DI factories
- `src/rpa_recorder/api/schemas/*.py` — request/response models
- `src/rpa_recorder/browser/executor.py` — adds `event_emitter` parameter (concrete contract)
- `tests/test_api_*.py`
