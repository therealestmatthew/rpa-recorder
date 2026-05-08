"""ARQ medallion promotion jobs.

`promote_bronze_to_silver(ctx, recording_id)` — wraps the silver promotion
core. Idempotent.

`promote_silver_to_gold(ctx, recording_id=None)` — recomputes hot gold
(SQLAlchemy upserts) and cold gold (DuckDB → Parquet). Distributed lock
via Redis `SET NX EX` ensures only one worker holds the cold-Parquet
write at a time.
"""

import asyncio
from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog

if TYPE_CHECKING:
    from rpa_recorder.medallion.bronze_store import LocalFilesystemStore

_log = structlog.get_logger(__name__)

_GOLD_LOCK_KEY = "lock:gold_promote"
_GOLD_LOCK_TTL_S = 600


async def promote_bronze_to_silver(
    ctx: dict[str, Any],
    *,
    recording_id: str,
) -> dict[str, Any]:
    """Re-derive `RecordedActionRow` rows from a recording's bronze JSONL."""
    from rpa_recorder.medallion.silver import promote_bronze_to_silver as _silver  # noqa: PLC0415
    from rpa_recorder.storage.db import get_session  # noqa: PLC0415

    engine = ctx["db_engine"]
    bronze_store: LocalFilesystemStore = ctx["bronze_store"]
    log = _log.bind(recording_id=recording_id, job_id=ctx.get("job_id"))

    rid = UUID(recording_id)
    async with get_session(engine) as db:
        inserted = await _silver(db, bronze_store, rid)

    log.info("bronze_to_silver_complete", inserted=inserted)
    return {"status": "ok", "inserted": inserted}


async def promote_silver_to_gold(
    ctx: dict[str, Any],
    *,
    recording_id: str | None = None,
) -> dict[str, Any]:
    """Recompute hot + cold gold tables. Held under a Redis `SET NX EX` lock."""
    from rpa_recorder.config import Config  # noqa: PLC0415
    from rpa_recorder.medallion.gold_cold import ColdGold  # noqa: PLC0415
    from rpa_recorder.medallion.gold_hot import recompute_gold_hot  # noqa: PLC0415
    from rpa_recorder.storage.db import get_session  # noqa: PLC0415

    engine = ctx["db_engine"]
    redis = ctx["redis"]
    config: Config = ctx.get("config") or Config()
    log = _log.bind(recording_id=recording_id, job_id=ctx.get("job_id"))

    worker_id = str(ctx.get("worker_id") or "unknown")
    acquired = await redis.set(_GOLD_LOCK_KEY, worker_id, nx=True, ex=_GOLD_LOCK_TTL_S)
    if not acquired:
        log.info("gold_promote_lock_held; skipping")
        return {"status": "skipped", "reason": "lock_held"}

    cold = ColdGold(config.gold_cold_root)
    try:
        async with get_session(engine) as db:
            hot_upserts = await recompute_gold_hot(
                db, recording_id=UUID(recording_id) if recording_id else None
            )

        async with get_session(engine) as db:
            errors: list[str] = []
            try:
                async with asyncio.TaskGroup() as tg:
                    tg.create_task(cold.recompute_classifier_accuracy(db))
                    tg.create_task(cold.recompute_llm_costs_daily(db))
                    tg.create_task(cold.recompute_training_data(db))
                    if recording_id:
                        tg.create_task(
                            cold.recompute_replay_scripts(db, UUID(recording_id))
                        )
            except* Exception as eg:
                for exc in eg.exceptions:
                    errors.append(f"{type(exc).__name__}: {exc}")
                    log.warning("cold_recompute_partial_failure", error=str(exc))
    finally:
        try:
            await redis.delete(_GOLD_LOCK_KEY)
        except Exception as exc:
            log.warning("gold_promote_lock_release_failed", error=str(exc))

    log.info("gold_promote_complete", hot_upserts=hot_upserts, cold_errors=len(errors))
    return {
        "status": "ok",
        "hot_upserts": hot_upserts,
        "cold_errors": errors,
    }
