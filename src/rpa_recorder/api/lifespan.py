"""Startup / shutdown wiring for the FastAPI control plane.

Constructs the process-singletons (engine, redis, queue pool, ws manager) on
startup and tears them down in reverse order. Reverse-order matters because
the queue pool's in-flight jobs publish through redis, and the ws manager
reads from redis — closing redis first risks `ConnectionError` log spam on
shutdown.
"""

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import structlog
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import create_async_engine

from rpa_recorder.api.streaming import WebSocketManager
from rpa_recorder.config import Config
from rpa_recorder.queues.protocol import make_queue_pool
from rpa_recorder.queues.replay_handler import make_replay_handler

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from fastapi import FastAPI


_log = structlog.get_logger(__name__)


async def _noop_handler(_pool: object, **_kwargs: object) -> dict[str, str]:
    """Stub for jobs deferred to M11.5 (gold promotion, compaction, prune)."""
    return {"status": "deferred", "reason": "M11.5 not active"}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Construct process-singletons; tear down in reverse order."""
    config: Config = getattr(app.state, "config", None) or Config()
    app.state.config = config

    engine = getattr(app.state, "engine", None)
    if engine is None:
        engine = create_async_engine(config.database_url, future=True)
        app.state.engine = engine

    redis = getattr(app.state, "redis", None)
    if redis is None:
        redis = Redis.from_url(config.redis_url, max_connections=20)
        app.state.redis = redis

    queue_pool = getattr(app.state, "queue_pool", None)
    if queue_pool is None:
        registry = {
            "replay_run": make_replay_handler(engine),
            "promote_silver_to_gold": _noop_handler,
            "compact_bronze_to_parquet": _noop_handler,
            "prune_old_artifacts": _noop_handler,
        }
        queue_pool = await make_queue_pool(
            config.queue_backend,
            redis=redis,
            registry=registry,
            redis_url=config.redis_url,
        )
        app.state.queue_pool = queue_pool

    ws_manager = getattr(app.state, "ws_manager", None)
    if ws_manager is None:
        ws_manager = WebSocketManager(
            redis=redis,
            buffer_size=config.ws_event_buffer_size,
            dedup_window=config.api_event_dedup_window,
            heartbeat_s=config.ws_heartbeat_s,
        )
        app.state.ws_manager = ws_manager

    _log.info("api_startup_complete", queue_backend=config.queue_backend)
    try:
        yield
    finally:
        # Reverse order: ws → queue → redis → engine.
        await ws_manager.close()
        await queue_pool.close()
        try:
            await redis.aclose()
        except Exception as exc:
            _log.warning("api_redis_close_failed", error=str(exc))
        await engine.dispose()
        _log.info("api_shutdown_complete")
