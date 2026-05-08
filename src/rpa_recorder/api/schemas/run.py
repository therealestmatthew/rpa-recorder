"""Pydantic schemas for `/runs` and `/recordings/{id}/replay` HTTP endpoints."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class RunStatus(BaseModel):
    """Lightweight projection returned by `GET /runs`."""

    id: UUID
    recording_id: UUID
    started_at: datetime
    ended_at: datetime | None
    status: str


class RunDetail(BaseModel):
    """Full run payload returned by `GET /runs/{id}`."""

    id: UUID
    recording_id: UUID
    started_at: datetime
    ended_at: datetime | None
    status: str
    summary: str | None
    parameter_values: dict[str, str]
    executions: list[dict[str, Any]]


class ReplayRequest(BaseModel):
    """Body of `POST /recordings/{id}/replay`."""

    parameters: dict[str, str] = Field(default_factory=dict)


class ReplayResponse(BaseModel):
    """Body of `POST /recordings/{id}/replay`."""

    run_id: UUID
    job_id: str
    status: str  # "queued"


class CancelResponse(BaseModel):
    """Body of `POST /runs/{id}/cancel`."""

    run_id: UUID
    cancelled: bool
