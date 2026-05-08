"""`POST /recordings/{id}/replay` — enqueues a `replay_run` job."""

from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException

from rpa_recorder.api.dependencies import get_queue_pool, get_session
from rpa_recorder.api.schemas import ReplayRequest, ReplayResponse
from rpa_recorder.storage.repositories import RecordingRepository

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from rpa_recorder.queues import QueuePool


router = APIRouter(prefix="/recordings", tags=["replay"])


@router.post("/{rid}/replay", response_model=ReplayResponse, status_code=202)
async def start_replay(
    rid: UUID,
    body: ReplayRequest,
    session: AsyncSession = Depends(get_session),
    pool: QueuePool = Depends(get_queue_pool),
) -> ReplayResponse:
    if await RecordingRepository(session).get(rid) is None:
        raise HTTPException(status_code=404, detail=f"recording {rid} not found")
    run_id = uuid4()
    result = await pool.enqueue_job(
        "replay_run",
        _queue_name="replay_queue",
        run_id=str(run_id),
        recording_id=str(rid),
        params=dict(body.parameters),
    )
    return ReplayResponse(run_id=run_id, job_id=result.job_id, status=result.status)
