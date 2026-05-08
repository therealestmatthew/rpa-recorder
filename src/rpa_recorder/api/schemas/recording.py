"""Pydantic schemas for `/recordings` HTTP endpoints."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class RecordingSummary(BaseModel):
    """Lightweight projection returned by `GET /recordings`."""

    id: UUID
    name: str
    created_at: datetime
    action_count: int


class RecordingDetail(BaseModel):
    """Full recording payload returned by `GET /recordings/{id}`."""

    id: UUID
    name: str
    description: str | None
    created_at: datetime
    created_by: str | None
    starting_url: str
    parameters: dict[str, dict[str, Any]]
    tags: list[str]
    actions: list[dict[str, Any]]
    network_log: list[dict[str, Any]]
