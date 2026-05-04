"""Audit log model for Anthropic SDK invocations."""

from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class LLMCall(BaseModel):
    """A single Anthropic SDK invocation, captured for observability and cost tracking."""

    id: UUID = Field(default_factory=uuid4)
    called_for: Literal["classify", "recover"]
    model: str
    prompt: str
    response: str
    recording_id: UUID | None = None
    run_id: UUID | None = None
    action_id: UUID | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: int
    created_at: datetime
    error: str | None = None
