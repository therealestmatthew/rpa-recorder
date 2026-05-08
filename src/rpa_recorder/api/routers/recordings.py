"""`GET /recordings` and `GET /recordings/{id}`."""

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from rpa_recorder.api.dependencies import get_session
from rpa_recorder.api.schemas import RecordingDetail, RecordingSummary
from rpa_recorder.storage.repositories import RecordingRepository

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


router = APIRouter(prefix="/recordings", tags=["recordings"])


@router.get("", response_model=list[RecordingSummary])
async def list_recordings(
    session: AsyncSession = Depends(get_session),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[RecordingSummary]:
    summaries = await RecordingRepository(session).list()
    sliced = summaries[offset : offset + limit]
    return [
        RecordingSummary(
            id=s.id,
            name=s.name,
            created_at=s.created_at,
            action_count=s.action_count,
        )
        for s in sliced
    ]


@router.get("/{rid}", response_model=RecordingDetail)
async def get_recording(
    rid: UUID,
    session: AsyncSession = Depends(get_session),
) -> RecordingDetail:
    recording = await RecordingRepository(session).get(rid)
    if recording is None:
        raise HTTPException(status_code=404, detail=f"recording {rid} not found")
    return RecordingDetail(
        id=recording.id,
        name=recording.name,
        description=recording.description,
        created_at=recording.created_at,
        created_by=recording.created_by,
        starting_url=recording.starting_url,
        parameters={k: v.model_dump() for k, v in recording.parameters.items()},
        tags=list(recording.tags),
        actions=[a.model_dump(mode="json") for a in recording.actions],
        network_log=[n.model_dump(mode="json") for n in recording.network_log],
    )
