"""`ArqQueuePool` — `QueuePool` Protocol implementation backed by ARQ + Redis (M11.5).

Talks to the same Redis instance ARQ workers drain. `enqueue_job(...)`
writes to a queue's ZSET; `queue_size(...)` reads it; `cancel(...)`
sets the same `cancel:{run_id}` flag the in-process backend uses, so
handlers (in either backend) check it the same way.

Constructed via `make_queue_pool("arq", redis=..., registry={})` — the
`registry` argument is unused because ARQ workers carry their own
function table; it's kept for Protocol parity with the in-process pool.
"""

from typing import TYPE_CHECKING, Any
from uuid import uuid4

import structlog

from rpa_recorder.queues.protocol import EnqueueResult

if TYPE_CHECKING:
    from arq.connections import ArqRedis
    from redis.asyncio import Redis

_log = structlog.get_logger(__name__)


class ArqQueuePool:
    """ARQ-backed implementation of `QueuePool`.

    Holds a redis client (typed `redis.asyncio.Redis`) used for cancellation
    and depth queries, and an `ArqRedis` pool used for enqueueing. The
    same Redis instance backs both — they're separate handles only because
    ARQ's job submission API needs its own session.
    """

    def __init__(self, *, redis: Redis, arq_pool: ArqRedis) -> None:
        self._redis = redis
        self._arq = arq_pool
        self._closed = False

    @property
    def redis(self) -> Redis:
        return self._redis

    async def enqueue_job(
        self,
        function: str,
        *,
        _queue_name: str = "replay_queue",
        **kwargs: Any,
    ) -> EnqueueResult:
        if self._closed:
            msg = "ArqQueuePool is closed"
            raise RuntimeError(msg)
        job_id = kwargs.pop("_job_id", None) or uuid4().hex
        job = await self._arq.enqueue_job(
            function,
            _queue_name=_queue_name,
            _job_id=job_id,
            **kwargs,
        )
        if job is None:
            return EnqueueResult(job_id=job_id, status="failed")
        return EnqueueResult(job_id=job.job_id, status="queued")

    async def queue_size(self, queue_name: str) -> int:
        """Approximate ARQ queue depth via the Redis ZSET length."""
        try:
            depth = await self._redis.zcard(queue_name)
        except Exception as exc:
            _log.warning("queue_size_failed", queue=queue_name, error=str(exc))
            return 0
        return int(depth)

    async def cancel(self, run_id: str) -> bool:
        """Set `cancel:{run_id}` so any handler checking the flag sees it."""
        try:
            new = await self._redis.set(
                f"cancel:{run_id}", "1", ex=3600, nx=True
            )
        except Exception as exc:
            _log.warning("cancel_redis_set_failed", run_id=run_id, error=str(exc))
            return False
        return bool(new)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await self._arq.close()
        except Exception as exc:
            _log.warning("arq_pool_close_failed", error=str(exc))


__all__ = ["ArqQueuePool"]
