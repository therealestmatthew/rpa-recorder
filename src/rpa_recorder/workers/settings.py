"""ARQ `WorkerSettings` classes — one per queue (M11.5).

Two workers run as separate processes, sharing the same job registry but
with different queue names and `max_jobs`:

- `ReplayWorkerSettings(queue_name="replay_queue", max_jobs=2)` — drains
  replay jobs (heavyweight: each spawns a `BrowserSession`).
- `MedallionWorkerSettings(queue_name="medallion_queue", max_jobs=10)` —
  drains promotion / compaction / prune (IO-bound).

Both are spawned via:

    arq rpa_recorder.workers.settings.ReplayWorkerSettings
    arq rpa_recorder.workers.settings.MedallionWorkerSettings

`on_startup` builds the shared `AsyncEngine`, `LocalFilesystemStore`, and
attaches them to `ctx`. `on_shutdown` disposes them. The Redis client
is provided by ARQ itself.
"""

from typing import TYPE_CHECKING, Any, ClassVar

import structlog
from arq import cron
from arq.connections import RedisSettings

from rpa_recorder.config import Config
from rpa_recorder.workers.jobs import (
    classify_recording,
    compact_bronze_to_parquet,
    generate_run_summary,
    promote_bronze_to_silver,
    promote_silver_to_gold,
    prune_old_artifacts,
    replay_run,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine


_log = structlog.get_logger(__name__)


def _redis_settings_from_url(url: str) -> RedisSettings:
    """Parse a redis URL into ARQ's `RedisSettings`."""
    return RedisSettings.from_dsn(url)


async def _on_startup(ctx: dict[str, Any]) -> None:
    """Populate `ctx` with shared resources before the worker drains jobs."""
    from rpa_recorder.medallion.bronze_store import LocalFilesystemStore  # noqa: PLC0415
    from rpa_recorder.storage.db import create_engine, init_db  # noqa: PLC0415

    config = Config()
    engine = create_engine(config.database_url)
    await init_db(engine)
    bronze_store = LocalFilesystemStore(config.bronze_root)

    ctx["config"] = config
    ctx["db_engine"] = engine
    ctx["bronze_store"] = bronze_store
    _log.info("worker_startup", queue=ctx.get("queue_name"))


async def _on_shutdown(ctx: dict[str, Any]) -> None:
    """Tear down shared resources on graceful shutdown."""
    engine = ctx.get("db_engine")
    if engine is not None:
        await engine.dispose()
    _log.info("worker_shutdown", queue=ctx.get("queue_name"))


_FUNCTIONS: list[Callable[..., Coroutine[Any, Any, Any]]] = [
    replay_run,
    classify_recording,
    generate_run_summary,
    promote_bronze_to_silver,
    promote_silver_to_gold,
    compact_bronze_to_parquet,
    prune_old_artifacts,
]


_CRON_JOBS = [
    cron(promote_silver_to_gold, hour=set(range(24)), minute={0}, run_at_startup=False),
    cron(compact_bronze_to_parquet, minute={0, 15, 30, 45}, run_at_startup=False),
    cron(prune_old_artifacts, hour={3}, minute={0}, run_at_startup=False),
]


class WorkerSettings:
    """Shared base. Subclass to set `queue_name` + `max_jobs` per queue."""

    queue_name: ClassVar[str] = "replay_queue"
    max_jobs: ClassVar[int] = 2
    redis_settings: ClassVar[RedisSettings] = _redis_settings_from_url(Config().redis_url)
    keep_result: ClassVar[int] = Config().worker_keep_result
    job_timeout: ClassVar[int] = Config().worker_replay_job_timeout
    shutdown_timeout: ClassVar[int] = Config().worker_shutdown_timeout
    functions: ClassVar[list[Any]] = _FUNCTIONS
    cron_jobs: ClassVar[list[Any]] = _CRON_JOBS
    on_startup = staticmethod(_on_startup)
    on_shutdown = staticmethod(_on_shutdown)


class ReplayWorkerSettings(WorkerSettings):
    """Replay queue. Browsers are heavyweight — cap concurrency tightly."""

    queue_name: ClassVar[str] = "replay_queue"
    max_jobs: ClassVar[int] = Config().worker_replay_max_jobs


class MedallionWorkerSettings(WorkerSettings):
    """Medallion queue. IO-bound — fan out higher."""

    queue_name: ClassVar[str] = "medallion_queue"
    max_jobs: ClassVar[int] = Config().worker_medallion_max_jobs


__all__ = [
    "MedallionWorkerSettings",
    "ReplayWorkerSettings",
    "WorkerSettings",
]
