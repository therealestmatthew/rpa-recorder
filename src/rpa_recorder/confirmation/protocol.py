"""Protocols + Pydantic models for the M11 confirmation pipeline.

Three Protocols (`Filter`, `ReviewMode`, `Renderer`) define the plugin axes;
`Decision`, `ActionReviewResult`, and `ReviewSummary` are the structured
events the runner emits and persists.
"""

from collections.abc import Awaitable, Callable
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol
from uuid import UUID

from pydantic import BaseModel, Field

from rpa_recorder.models import RecordedAction, Recording, SemanticIntent

if TYPE_CHECKING:
    from rich.console import RenderableType


class Decision(StrEnum):
    """User verdict on a single classified action."""

    ACCEPT = "accept"
    RELABEL = "relabel"
    SKIP = "skip"


class ActionReviewResult(BaseModel):
    """One row in the review log: the user's call on one action."""

    action_id: UUID
    decision: Decision
    new_label: SemanticIntent | None = None
    reviewed_at: datetime


class ReviewSummary(BaseModel):
    """End-of-pass tally returned by `ConfirmationRunner.run`."""

    recording_id: UUID
    total_candidates: int
    accepted: int
    relabeled: int
    skipped: int
    duration_s: float
    results: list[ActionReviewResult] = Field(default_factory=list)


OnDecision = Callable[[ActionReviewResult], Awaitable[None]]


class Filter(Protocol):
    """Selects which actions need review."""

    name: str

    def select(self, recording: Recording, *, threshold: float) -> list[RecordedAction]: ...


class Renderer(Protocol):
    """Formats action context for the user. Pure formatting, no I/O."""

    name: str

    def render_action(
        self,
        action: RecordedAction,
        *,
        context: dict[str, Any] | None = None,
    ) -> RenderableType: ...

    def render_summary(self, summary: ReviewSummary) -> RenderableType: ...

    def render_intent_batch(
        self,
        intent: SemanticIntent,
        actions: list[RecordedAction],
    ) -> RenderableType: ...


class ReviewMode(Protocol):
    """Drives the interactive loop over the candidate list."""

    name: str

    async def review(
        self,
        candidates: list[RecordedAction],
        *,
        renderer: Renderer,
        on_decision: OnDecision,
    ) -> list[ActionReviewResult]: ...


__all__ = [
    "ActionReviewResult",
    "Decision",
    "Filter",
    "OnDecision",
    "Renderer",
    "ReviewMode",
    "ReviewSummary",
]
