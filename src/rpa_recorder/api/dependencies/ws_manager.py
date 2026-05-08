"""`get_ws_manager()` — returns the process-singleton `WebSocketManager`."""

from typing import TYPE_CHECKING, cast

from fastapi import Request

if TYPE_CHECKING:
    from rpa_recorder.api.streaming import WebSocketManager


def get_ws_manager(request: Request) -> WebSocketManager:
    """Return the WebSocketManager instance constructed in `lifespan`."""

    return cast("WebSocketManager", request.app.state.ws_manager)
