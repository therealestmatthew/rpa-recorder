"""`WebSocket /runs/{id}/stream` — bridges Redis pub/sub to subscribers."""

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends, WebSocket

from rpa_recorder.api.dependencies import get_ws_manager

if TYPE_CHECKING:
    from rpa_recorder.api.streaming import WebSocketManager


router = APIRouter(tags=["streaming"])


@router.websocket("/runs/{rid}/stream")
async def stream(
    websocket: WebSocket,
    rid: UUID,
    manager: WebSocketManager = Depends(get_ws_manager),
) -> None:
    await websocket.accept()
    await manager.subscribe(rid, websocket)
