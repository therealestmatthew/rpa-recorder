"""Pydantic schemas for `/medallion/*` HTTP endpoints."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class RecomputeRequest(BaseModel):
    """Body of `POST /medallion/recompute`."""

    recording_id: UUID | None = None


class RecomputeResponse(BaseModel):
    """Body of `POST /medallion/recompute` and `POST /medallion/compact`."""

    job_id: str
    status: str  # "queued" | "deferred"
    reason: str | None = None


class MedallionStatus(BaseModel):
    """Body of `GET /medallion/status`."""

    bronze_artifact_count: int = 0
    bronze_recordings: int = 0
    last_replay_at: datetime | None = None
    queue_backend: str
    notes: list[str] = Field(default_factory=list)
