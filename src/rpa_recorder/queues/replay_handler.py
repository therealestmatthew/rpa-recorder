"""In-process implementation of the `replay_run` job.

Wires `Executor` + `RecoveryEngine` to publish events through the same
`publish_progress` helper M11.5's ARQ worker uses. Imported lazily so the
queues package import cost stays cheap for callers that only need the
Protocol.
"""

import functools
from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog

from rpa_recorder.queues.events import publish_progress

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from sqlalchemy.ext.asyncio import AsyncEngine

    from rpa_recorder.queues.in_process import InProcessQueuePool


_log = structlog.get_logger(__name__)


async def run_replay(
    pool: InProcessQueuePool,
    *,
    run_id: str,
    recording_id: str,
    params: dict[str, Any] | None = None,
    engine: AsyncEngine,
) -> dict[str, Any]:
    """Open a browser, replay the recording, persist a `RunResult`.

    Imports `playwright`, the storage layer, and recovery strategies inside
    the function body so the queues package import stays cheap and so a unit
    test that monkey-patches the pool's registry doesn't need a browser
    available.
    """
    # Local imports — keep the queues/__init__.py cold-start cheap.
    from rpa_recorder.browser.executor import Executor  # noqa: PLC0415
    from rpa_recorder.browser.session import BrowserSession  # noqa: PLC0415
    from rpa_recorder.config import Config  # noqa: PLC0415
    from rpa_recorder.recovery import (  # noqa: PLC0415
        RecoveryContext,
        RecoveryEngine,
        default_strategies,
    )
    from rpa_recorder.storage.db import get_session  # noqa: PLC0415
    from rpa_recorder.storage.repositories import (  # noqa: PLC0415
        RecordingRepository,
        RunResultRepository,
    )

    config = Config()
    redis = pool.redis
    log = _log.bind(run_id=run_id, recording_id=recording_id)

    rid = UUID(recording_id)
    async with get_session(engine) as session:
        recording = await RecordingRepository(session).get(rid)
    if recording is None:
        await publish_progress(
            redis,
            run_id,
            {"type": "run_failed", "run_id": run_id, "error": "recording_not_found"},
        )
        log.warning("recording_not_found")
        return {"status": "failed", "reason": "recording_not_found"}

    emitter = functools.partial(_emit_via_redis, redis, run_id)

    async with BrowserSession(headless=config.default_headless) as session:
        recovery_engine = RecoveryEngine(
            default_strategies(),
            config=config,
            event_emitter=emitter,
        )
        executor = Executor(
            session.page,
            recording,
            screenshots_dir=config.screenshots_dir,
            dom_dir=config.dom_dir,
            parameter_values=params or {},
            run_id=UUID(run_id),
            recovery_engine=recovery_engine,
            recovery_context=RecoveryContext(),
            event_emitter=emitter,
        )
        result = await executor.run()

    async with get_session(engine) as db:
        await RunResultRepository(db).save(result)

    log.info("replay_complete", status=result.status.value)
    return {"status": result.status.value, "run_id": run_id}


async def _emit_via_redis(
    redis: Any, run_id: str, event_type: str, payload: dict[str, Any]
) -> None:
    """Adapter from `(event_type, payload)` callbacks → `publish_progress`."""
    event = {"type": event_type, **payload}
    event.setdefault("run_id", run_id)
    await publish_progress(redis, run_id, event)


def make_replay_handler(
    engine: AsyncEngine,
) -> Callable[..., Awaitable[dict[str, Any]]]:
    """Return a closure suitable for registering with `InProcessQueuePool`."""

    async def _handler(
        pool: InProcessQueuePool,
        *,
        run_id: str,
        recording_id: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return await run_replay(
            pool,
            run_id=run_id,
            recording_id=recording_id,
            params=params,
            engine=engine,
        )

    return _handler


__all__ = ["make_replay_handler", "run_replay"]
