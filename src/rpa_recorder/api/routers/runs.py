"""`GET /runs`, `GET /runs/{id}`, `POST /runs/{id}/cancel`."""

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from rpa_recorder.api.dependencies import get_queue_pool, get_session
from rpa_recorder.api.schemas import CancelResponse, RunDetail, RunStatus
from rpa_recorder.storage.repositories import RunResultRepository

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from rpa_recorder.queues import QueuePool


router = APIRouter(prefix="/runs", tags=["runs"])


@router.get("", response_model=list[RunStatus])
async def list_runs(
    session: AsyncSession = Depends(get_session),
    recording_id: UUID | None = Query(None),
) -> list[RunStatus]:
    if recording_id is None:
        return []
    summaries = await RunResultRepository(session).list_for_recording(recording_id)
    return [
        RunStatus(
            id=s.id,
            recording_id=s.recording_id,
            started_at=s.started_at,
            ended_at=s.ended_at,
            status=s.status.value,
        )
        for s in summaries
    ]


@router.get("/{rid}", response_model=RunDetail)
async def get_run(
    rid: UUID,
    session: AsyncSession = Depends(get_session),
) -> RunDetail:
    run = await RunResultRepository(session).get(rid)
    if run is None:
        raise HTTPException(status_code=404, detail=f"run {rid} not found")
    return RunDetail(
        id=run.id,
        recording_id=run.recording_id,
        started_at=run.started_at,
        ended_at=run.ended_at,
        status=run.status.value,
        summary=run.summary,
        parameter_values=dict(run.parameter_values),
        executions=[e.model_dump(mode="json") for e in run.executions],
    )


@router.post("/{rid}/cancel", response_model=CancelResponse)
async def cancel_run(
    rid: UUID,
    pool: QueuePool = Depends(get_queue_pool),
) -> CancelResponse:
    cancelled = await pool.cancel(str(rid))
    return CancelResponse(run_id=rid, cancelled=cancelled)
