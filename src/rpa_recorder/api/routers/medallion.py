"""`POST /medallion/recompute`, `POST /medallion/compact`, `GET /medallion/status`.

Under the in-process queue backend (M12 default), recompute / compact return
202 with `status="deferred"` because gold-promotion logic ships in M11.5.
The contract is stable across backends.
"""

from typing import TYPE_CHECKING
from uuid import uuid4

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from rpa_recorder.api.dependencies import get_config, get_queue_pool, get_session
from rpa_recorder.api.schemas import MedallionStatus, RecomputeRequest, RecomputeResponse
from rpa_recorder.storage.db import BronzeArtifactRow, RecordingRow, RunResultRow

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from rpa_recorder.config import Config
    from rpa_recorder.queues import QueuePool


router = APIRouter(prefix="/medallion", tags=["medallion"])


@router.post("/recompute", response_model=RecomputeResponse, status_code=202)
async def recompute(
    body: RecomputeRequest,
    pool: QueuePool = Depends(get_queue_pool),
    config: Config = Depends(get_config),
) -> RecomputeResponse:
    if config.queue_backend == "in_process":
        return RecomputeResponse(
            job_id=uuid4().hex,
            status="deferred",
            reason="gold promotion ships in M11.5",
        )
    result = await pool.enqueue_job(
        "promote_silver_to_gold",
        _queue_name="medallion_queue",
        recording_id=str(body.recording_id) if body.recording_id else None,
    )
    return RecomputeResponse(job_id=result.job_id, status=result.status)


@router.post("/compact", response_model=RecomputeResponse, status_code=202)
async def compact(
    pool: QueuePool = Depends(get_queue_pool),
    config: Config = Depends(get_config),
) -> RecomputeResponse:
    if config.queue_backend == "in_process":
        return RecomputeResponse(
            job_id=uuid4().hex,
            status="deferred",
            reason="bronze compaction ships in M11.5",
        )
    result = await pool.enqueue_job(
        "compact_bronze_to_parquet",
        _queue_name="medallion_queue",
    )
    return RecomputeResponse(job_id=result.job_id, status=result.status)


@router.get("/status", response_model=MedallionStatus)
async def status(
    session: AsyncSession = Depends(get_session),
    config: Config = Depends(get_config),
) -> MedallionStatus:
    artifact_count = (await session.execute(select(func.count(BronzeArtifactRow.id)))).scalar_one()
    recordings = (await session.execute(select(func.count(RecordingRow.id)))).scalar_one()
    last_replay = (await session.execute(select(func.max(RunResultRow.started_at)))).scalar_one()
    notes: list[str] = []
    if config.queue_backend == "in_process":
        notes.append("queue_backend=in_process: gold promotion + compaction deferred to M11.5")
    return MedallionStatus(
        bronze_artifact_count=int(artifact_count or 0),
        bronze_recordings=int(recordings or 0),
        last_replay_at=last_replay,
        queue_backend=config.queue_backend,
        notes=notes,
    )
