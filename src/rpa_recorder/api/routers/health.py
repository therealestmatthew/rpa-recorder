"""Health probes — `/healthz` (liveness) and `/readyz` (dependency check)."""

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends
from sqlalchemy import text
from starlette.responses import JSONResponse

from rpa_recorder.api.dependencies import get_queue_pool, get_redis, get_session

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

    from rpa_recorder.queues import QueuePool


router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict[str, bool]:
    """Cheap liveness probe — no dependency calls."""
    return {"ok": True}


@router.get("/readyz")
async def readyz(
    redis: Redis = Depends(get_redis),
    session: AsyncSession = Depends(get_session),
    pool: QueuePool = Depends(get_queue_pool),
) -> JSONResponse:
    """Ping each dependency once. 503 on any failure."""
    status = {"db": "ok", "redis": "ok", "queue": "ok"}
    try:
        await session.execute(text("SELECT 1"))
    except Exception:
        status["db"] = "fail"
    try:
        await redis.ping()  # type: ignore[misc]
    except Exception:
        status["redis"] = "fail"
    try:
        await pool.queue_size("replay_queue")
    except Exception:
        status["queue"] = "fail"
    code = 200 if all(v == "ok" for v in status.values()) else 503
    return JSONResponse(status, status_code=code)
