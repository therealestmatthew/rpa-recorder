"""`InProcessQueuePool` — runs job handlers in the FastAPI event loop.

Used as the M12 default until M11.5 ships an `ArqQueuePool`. Each registered
job runs under an `asyncio.Task` gated by a per-queue `asyncio.Semaphore`
(`replay_queue=2`, `medallion_queue=10`). Every job run publishes its
lifecycle events through `publish_progress(redis, run_id, ...)` exactly the
way an ARQ worker would, so the WebSocket layer reads from Redis without
caring which backend produced the events.

Cancellation: `cancel(run_id)` writes `cancel:{run_id}` in Redis (so M11.5's
ARQ worker would see the same flag) AND sets a per-run `asyncio.Event` that
in-process handlers can poll via `is_cancelled(run_id)` for a fast local
check between actions.
"""

import asyncio
from contextlib import suppress
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import structlog

from rpa_recorder.queues.events import publish_progress
from rpa_recorder.queues.protocol import EnqueueResult

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from redis.asyncio import Redis


_log = structlog.get_logger(__name__)


_DEFAULT_QUEUE_LIMITS: dict[str, int] = {
    "replay_queue": 2,
    "medallion_queue": 10,
}


class _JobState:
    __slots__ = ("job_id", "queue_name", "status", "task")

    def __init__(self, job_id: str, queue_name: str, task: asyncio.Task[Any]) -> None:
        self.job_id = job_id
        self.queue_name = queue_name
        self.status = "queued"
        self.task = task


class InProcessQueuePool:
    """Run jobs in-process with bounded per-queue concurrency."""

    def __init__(
        self,
        *,
        redis: Redis,
        registry: dict[str, Callable[..., Awaitable[Any]]],
        queue_limits: dict[str, int] | None = None,
        shutdown_grace_s: float = 30.0,
    ) -> None:
        self._redis = redis
        self._registry = dict(registry)
        limits = dict(_DEFAULT_QUEUE_LIMITS)
        if queue_limits:
            limits.update(queue_limits)
        self._semaphores: dict[str, asyncio.Semaphore] = {
            name: asyncio.Semaphore(cap) for name, cap in limits.items()
        }
        self._jobs: dict[str, _JobState] = {}
        self._cancel_events: dict[str, asyncio.Event] = {}
        self._shutdown_grace_s = shutdown_grace_s
        self._closed = False

    # ----- QueuePool surface ------------------------------------------------

    async def enqueue_job(
        self,
        function: str,
        *,
        _queue_name: str = "replay_queue",
        **kwargs: Any,
    ) -> EnqueueResult:
        if self._closed:
            msg = "InProcessQueuePool is closed"
            raise RuntimeError(msg)
        if _queue_name not in self._semaphores:
            msg = f"unknown queue {_queue_name!r}; known: {sorted(self._semaphores)}"
            raise ValueError(msg)
        handler = self._registry.get(function)
        if handler is None:
            msg = f"no handler registered for {function!r}; known: {sorted(self._registry)}"
            raise KeyError(msg)

        job_id = uuid4().hex
        # Pre-register a cancel event for the run if kwargs contain a run_id.
        run_id = kwargs.get("run_id")
        if isinstance(run_id, str) and run_id not in self._cancel_events:
            self._cancel_events[run_id] = asyncio.Event()

        task = asyncio.create_task(
            self._run_one(job_id, function, _queue_name, handler, kwargs),
            name=f"queue:{_queue_name}:{function}:{job_id}",
        )
        self._jobs[job_id] = _JobState(job_id=job_id, queue_name=_queue_name, task=task)
        return EnqueueResult(job_id=job_id, status="queued")

    async def queue_size(self, queue_name: str) -> int:
        return sum(
            1
            for j in self._jobs.values()
            if j.queue_name == queue_name and j.status in ("queued", "in_progress")
        )

    async def cancel(self, run_id: str) -> bool:
        try:
            new = await self._redis.set(f"cancel:{run_id}", "1", ex=3600, nx=True)
        except Exception as exc:
            _log.warning("cancel_redis_set_failed", run_id=run_id, error=str(exc))
            new = False
        event = self._cancel_events.get(run_id)
        if event is not None and not event.is_set():
            event.set()
        return bool(new)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        active = [j.task for j in self._jobs.values() if not j.task.done()]
        if not active:
            return
        try:
            await asyncio.wait_for(
                asyncio.gather(*active, return_exceptions=True),
                timeout=self._shutdown_grace_s,
            )
        except TimeoutError:
            for task in active:
                task.cancel()
            await asyncio.gather(*active, return_exceptions=True)

    # ----- helpers exposed to handlers --------------------------------------

    def is_cancelled(self, run_id: str) -> bool:
        """Cheap local cancel check — handlers can poll between actions."""
        event = self._cancel_events.get(run_id)
        return event is not None and event.is_set()

    @property
    def redis(self) -> Redis:
        """Underlying Redis client. Handlers use it to call `publish_progress`."""
        return self._redis

    # ----- internals --------------------------------------------------------

    async def _run_one(
        self,
        job_id: str,
        function: str,
        queue_name: str,
        handler: Callable[..., Awaitable[Any]],
        kwargs: dict[str, Any],
    ) -> None:
        sem = self._semaphores[queue_name]
        state = self._jobs[job_id]
        run_id = kwargs.get("run_id") if isinstance(kwargs.get("run_id"), str) else None
        log = _log.bind(job_id=job_id, function=function, queue=queue_name, run_id=run_id)
        try:
            async with sem:
                state.status = "in_progress"
                log.info("job_started")
                try:
                    await handler(self, **kwargs)
                except asyncio.CancelledError:
                    state.status = "cancelled"
                    log.info("job_cancelled")
                    if run_id is not None:
                        with suppress(Exception):
                            await publish_progress(
                                self._redis,
                                run_id,
                                {"type": "run_cancelled", "run_id": run_id},
                            )
                    raise
                except Exception as exc:
                    state.status = "failed"
                    log.warning("job_failed", error=str(exc), error_type=type(exc).__name__)
                    if run_id is not None:
                        with suppress(Exception):
                            await publish_progress(
                                self._redis,
                                run_id,
                                {
                                    "type": "run_failed",
                                    "run_id": run_id,
                                    "error": str(exc),
                                },
                            )
                else:
                    state.status = "complete"
                    log.info("job_complete")
        finally:
            # Keep terminal state visible for queue_size; let ARQ-style cleanup
            # of completed jobs run on a periodic sweep if/when added.
            pass


__all__ = ["InProcessQueuePool"]
