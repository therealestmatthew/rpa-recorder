"""ARQ `replay_run` job — drives a `BrowserSession` and an `Executor`.

Wraps the in-process `queues.replay_handler.run_replay` so the same code
runs in both backends. ARQ's `ctx` carries the shared engine + Redis
client populated in `WorkerSettings.on_startup`.

Browser-launch semaphore: ARQ's `max_jobs` already caps how many
`replay_run` invocations run concurrently in one worker process, so the
spec's belt-and-suspenders semaphore is redundant in v1. If we ever set
`max_jobs > worker_replay_max_jobs` for some reason, add a
`module-global asyncio.Semaphore(Config().worker_replay_max_jobs)` here.
"""

from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncEngine

_log = structlog.get_logger(__name__)


class _PoolShim:
    """Minimal shim with a `.redis` property — `run_replay` only reads that."""

    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    def is_cancelled(self, _run_id: str) -> bool:
        return False


async def replay_run(
    ctx: dict[str, Any],
    *,
    run_id: str,
    recording_id: str,
    params: dict[str, str] | None = None,
) -> dict[str, Any]:
    """ARQ-shaped replay handler. `ctx` carries `redis` + `db_engine`."""
    from rpa_recorder.queues.replay_handler import run_replay  # noqa: PLC0415

    redis: Redis = ctx["redis"]
    engine: AsyncEngine = ctx["db_engine"]
    log = _log.bind(run_id=run_id, recording_id=recording_id, job_id=ctx.get("job_id"))
    log.info("arq_replay_started")

    pool = _PoolShim(redis)
    result = await run_replay(
        pool,  # type: ignore[arg-type]
        run_id=run_id,
        recording_id=recording_id,
        params=params,
        engine=engine,
    )
    log.info("arq_replay_finished", status=result.get("status"))
    return result
