"""Router registry — one APIRouter per resource."""

from typing import TYPE_CHECKING

from rpa_recorder.api.routers.health import router as health_router
from rpa_recorder.api.routers.medallion import router as medallion_router
from rpa_recorder.api.routers.recordings import router as recordings_router
from rpa_recorder.api.routers.replay import router as replay_router
from rpa_recorder.api.routers.runs import router as runs_router
from rpa_recorder.api.routers.streaming import router as streaming_router

if TYPE_CHECKING:
    from fastapi import APIRouter


def all_routers() -> list[APIRouter]:
    """Order matters for `/docs` grouping but not for routing itself."""
    return [
        health_router,
        recordings_router,
        runs_router,
        replay_router,
        medallion_router,
        streaming_router,
    ]


__all__ = ["all_routers"]
