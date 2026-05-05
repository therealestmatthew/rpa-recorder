"""Replay execution models: attempts, recovery actions, results."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from rpa_recorder.models.actions import ElementSelector


class ExecutionStatus(StrEnum):
    """Lifecycle state of a single action or full run."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    RECOVERED = "recovered"
    SKIPPED = "skipped"
    AWAITING_CONFIRMATION = "awaiting_confirmation"


class FailureMode(StrEnum):
    """Coarse classification of why an action failed."""

    ELEMENT_NOT_FOUND = "element_not_found"
    ELEMENT_NOT_INTERACTABLE = "element_not_interactable"
    UNEXPECTED_MODAL = "unexpected_modal"
    NAVIGATION_FAILED = "navigation_failed"
    VALIDATION_ERROR = "validation_error"
    TIMEOUT = "timeout"
    NETWORK_ERROR = "network_error"
    UNKNOWN = "unknown"


class ExecutionAttempt(BaseModel):
    """One attempt at executing an action; multiple per `ActionExecution` if recovery runs.

    The `id` is generated up-front (rather than at DB save time) so bronze
    artifacts captured during the attempt — screenshot, DOM, a11y — can FK to
    the same id that lands in `execution_attempts.id`.
    """

    id: UUID = Field(default_factory=uuid4)
    attempt_number: int
    started_at: datetime
    ended_at: datetime | None = None
    status: ExecutionStatus
    selector_used: ElementSelector | None = None
    failure_mode: FailureMode | None = None
    error_message: str | None = None
    screenshot_path: str | None = None
    dom_snapshot_path: str | None = None
    accessibility_snapshot_path: str | None = None
    console_log: list[str] = Field(default_factory=list)
    js_errors: list[str] = Field(default_factory=list)


class RecoveryAction(BaseModel):
    """The recovery strategy chosen and its outcome for a failed action."""

    strategy: str
    rationale: str | None = None
    succeeded: bool
    new_selector: ElementSelector | None = None


class ActionExecution(BaseModel):
    """Aggregated outcome for one recorded action across all its attempts."""

    action_id: UUID
    status: ExecutionStatus
    attempts: list[ExecutionAttempt]
    recovery: RecoveryAction | None = None
    duration_ms: int | None = None


class RunResult(BaseModel):
    """Top-level result of replaying a `Recording`."""

    id: UUID = Field(default_factory=uuid4)
    recording_id: UUID
    started_at: datetime
    ended_at: datetime | None = None
    status: ExecutionStatus
    parameter_values: dict[str, str] = Field(default_factory=dict)
    executions: list[ActionExecution]
    summary: str | None = None
