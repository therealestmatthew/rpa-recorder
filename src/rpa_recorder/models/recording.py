"""`Recording`, `ParameterDef`, and `NetworkEvent` models."""

from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from rpa_recorder.models.actions import RecordedAction


class ParameterDef(BaseModel):
    """A named, typed parameter that callers supply at replay time."""

    name: str
    type: Literal["string", "number", "boolean", "secret"]
    default: str | None = None
    description: str | None = None


class NetworkEvent(BaseModel):
    """Lightweight, searchable record of an HTTP request observed during recording.

    The full HAR file is written separately to disk; this row stores metadata only.
    """

    timestamp: datetime
    method: str
    url: str
    status: int | None = None
    request_headers: dict[str, str] = Field(default_factory=dict)
    response_summary: str | None = None


class Recording(BaseModel):
    """A complete recorded workflow: actions, network log, parameters, tags."""

    id: UUID = Field(default_factory=uuid4)
    name: str
    description: str | None = None
    created_at: datetime
    created_by: str | None = None
    starting_url: str
    actions: list[RecordedAction]
    network_log: list[NetworkEvent] = Field(default_factory=list)
    parameters: dict[str, ParameterDef] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    source: str = "playwright"
