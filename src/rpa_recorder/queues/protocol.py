"""`QueuePool` Protocol — the seam between FastAPI routes and a worker queue.

Defaults to `InProcessQueuePool` (jobs run in the FastAPI loop). M11.5 ships an
`ArqQueuePool` next door without touching `api/`. Both publish progress through
`publish_progress(redis, run_id, event)` so the WebSocket path is identical.

Note on `queue_size` semantics: the in-process backend returns the count of
jobs currently active+pending for that queue (not strictly "depth waiting").
ARQ returns the true Redis ZSET depth. For backpressure both are good-enough
saturation signals.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from redis.asyncio import Redis


JobHandler = "Callable[..., Awaitable[Any]]"


@dataclass(frozen=True, slots=True)
class EnqueueResult:
    """Returned by `QueuePool.enqueue_job` so HTTP handlers don't depend on backend types."""

    job_id: str
    status: str  # "queued" | "in_progress" | "complete" | "failed" | "cancelled"


@runtime_checkable
class QueuePool(Protocol):
    """Minimum surface FastAPI routes need from a queue backend."""

    async def enqueue_job(
        self,
        function: str,
        *,
        _queue_name: str = "replay_queue",
        **kwargs: Any,
    ) -> EnqueueResult:
        """Enqueue `function` with `kwargs` onto `_queue_name`. Return its job id and status."""
        ...

    async def queue_size(self, queue_name: str) -> int:
        """Return the count of jobs active+pending for `queue_name`."""
        ...

    async def cancel(self, run_id: str) -> bool:
        """Mark `run_id` cancelled. Returns True iff a flag was newly set (idempotent)."""
        ...

    async def close(self) -> None:
        """Drain in-flight jobs and release resources."""
        ...


async def make_queue_pool(
    backend: str,
    *,
    redis: Redis,
    registry: dict[str, Callable[..., Awaitable[Any]]],
    redis_url: str | None = None,
) -> QueuePool:
    """Construct the configured backend.

    `backend == "in_process"` returns an `InProcessQueuePool`.
    `backend == "arq"` returns an `ArqQueuePool` (M11.5) — needs `redis_url`
    so it can build an `ArqRedis` pool against the same instance.
    """
    if backend == "in_process":
        from rpa_recorder.queues.in_process import InProcessQueuePool  # noqa: PLC0415

        return InProcessQueuePool(redis=redis, registry=registry)
    if backend == "arq":
        if redis_url is None:
            msg = "queue_backend=arq requires redis_url for ARQ pool construction"
            raise ValueError(msg)
        from arq import create_pool  # noqa: PLC0415
        from arq.connections import RedisSettings  # noqa: PLC0415

        from rpa_recorder.queues.arq import ArqQueuePool  # noqa: PLC0415

        arq_pool = await create_pool(RedisSettings.from_dsn(redis_url))
        return ArqQueuePool(redis=redis, arq_pool=arq_pool)
    msg = f"unknown queue_backend: {backend!r}"
    raise ValueError(msg)


__all__ = ["EnqueueResult", "JobHandler", "QueuePool", "make_queue_pool"]
