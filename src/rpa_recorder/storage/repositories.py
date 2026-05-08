"""Repositories: persist Pydantic models to SQLAlchemy rows and back.

The repository methods do **not** commit on their own — the `get_session()`
context manager in `db.py` owns transaction boundaries so callers can compose
multiple operations into a single unit of work.
"""

from datetime import datetime
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from rpa_recorder.models import (
    ActionExecution,
    ActionType,
    ClickPayload,
    ElementContext,
    ElementSelector,
    ExecutionAttempt,
    ExecutionStatus,
    FailureMode,
    InputPayload,
    NavigatePayload,
    NetworkEvent,
    ParameterDef,
    RecordedAction,
    Recording,
    RecoveryAction,
    RunResult,
    SelectPayload,
    SemanticIntent,
)
from rpa_recorder.storage.db import (
    ActionExecutionRow,
    BronzeArtifactRow,
    ExecutionAttemptRow,
    GoldRecordingMetricsRow,
    GoldRunDashboardRow,
    NetworkEventRow,
    RecordedActionRow,
    RecordingRow,
    RunResultRow,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from rpa_recorder.models.actions import ActionPayload


_PAYLOAD_TYPES: dict[ActionType, type[BaseModel]] = {
    ActionType.CLICK: ClickPayload,
    ActionType.INPUT: InputPayload,
    ActionType.NAVIGATE: NavigatePayload,
    ActionType.SELECT: SelectPayload,
}


def _payload_to_dict(payload: ActionPayload) -> dict[str, Any]:
    if isinstance(payload, BaseModel):
        return payload.model_dump()
    return dict(payload)


def _payload_from_dict(action_type: ActionType, data: dict[str, Any]) -> ActionPayload:
    cls = _PAYLOAD_TYPES.get(action_type)
    if cls is None:
        return dict(data)
    return cast("ActionPayload", cls.model_validate(data))


def _model_or_none(cls: type[BaseModel], data: dict[str, Any] | None) -> Any:
    if data is None:
        return None
    return cls.model_validate(data)


class RecordingSummary(BaseModel):
    """Lightweight projection used by `rpa list` and the API list endpoints."""

    id: UUID
    name: str
    created_at: datetime
    action_count: int


class RunResultSummary(BaseModel):
    """Projection for listing replay runs of a recording."""

    id: UUID
    recording_id: UUID
    started_at: datetime
    ended_at: datetime | None
    status: ExecutionStatus


class RecordingRepository:
    """CRUD over `Recording` aggregates (recording + actions + network log)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, recording: Recording) -> None:
        """Insert a new recording with all its actions and network events."""
        row = RecordingRow(
            id=str(recording.id),
            name=recording.name,
            description=recording.description,
            created_at=recording.created_at,
            created_by=recording.created_by,
            starting_url=recording.starting_url,
            parameters={k: v.model_dump() for k, v in recording.parameters.items()},
            tags=list(recording.tags),
        )
        for action in recording.actions:
            row.actions.append(self._action_to_row(action))
        for event in recording.network_log:
            row.network_events.append(self._network_to_row(event))
        self._session.add(row)
        await self._session.flush()

    async def get(self, recording_id: UUID) -> Recording | None:
        """Load a recording with eager-loaded actions and network events."""
        stmt = (
            select(RecordingRow)
            .where(RecordingRow.id == str(recording_id))
            .options(
                selectinload(RecordingRow.actions),
                selectinload(RecordingRow.network_events),
            )
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        if row is None:
            return None
        return self._row_to_recording(row)

    async def list(self) -> list[RecordingSummary]:
        """Return summary projections for every recording, newest-first."""
        action_count = (
            select(func.count(RecordedActionRow.id))
            .where(RecordedActionRow.recording_id == RecordingRow.id)
            .scalar_subquery()
        )
        stmt = select(
            RecordingRow.id,
            RecordingRow.name,
            RecordingRow.created_at,
            action_count.label("action_count"),
        ).order_by(RecordingRow.created_at.desc())
        result = await self._session.execute(stmt)
        return [
            RecordingSummary(
                id=UUID(row.id),
                name=row.name,
                created_at=row.created_at,
                action_count=int(row.action_count or 0),
            )
            for row in result.all()
        ]

    async def delete(self, recording_id: UUID) -> bool:
        """Delete a recording and cascade to its actions and network events."""
        row = await self._session.get(RecordingRow, str(recording_id))
        if row is None:
            return False
        await self._session.delete(row)
        await self._session.flush()
        return True

    async def update_action_classification(
        self,
        action_id: UUID,
        *,
        intent: SemanticIntent | None = None,
        user_confirmed: bool | None = None,
        user_label: str | None = None,
    ) -> None:
        """Per-action partial update for the M11 confirmation flow.

        The owning `get_session()` context commits; the runner uses one
        session per decision so a Ctrl+C-mid-pass keeps reviewed actions.
        """
        row = await self._session.get(RecordedActionRow, str(action_id))
        if row is None:
            msg = f"action {action_id} not found"
            raise LookupError(msg)
        if intent is not None:
            row.semantic_intent = intent.value
        if user_confirmed is not None:
            row.user_confirmed = user_confirmed
        if user_label is not None:
            row.user_label = user_label
        await self._session.flush()

    @staticmethod
    def _action_to_row(action: RecordedAction) -> RecordedActionRow:
        return RecordedActionRow(
            id=str(action.id),
            sequence=action.sequence,
            timestamp=action.timestamp,
            action_type=action.action_type.value,
            url=action.url,
            page_title=action.page_title,
            frame_url=action.frame_url,
            semantic_intent=action.semantic_intent.value,
            classification_confidence=action.classification_confidence,
            classification_reasoning=action.classification_reasoning,
            user_confirmed=action.user_confirmed,
            user_label=action.user_label,
            is_parameterized=action.is_parameterized,
            parameter_name=action.parameter_name,
            payload=_payload_to_dict(action.payload),
            selector=action.selector.model_dump() if action.selector else None,
            element_context=(
                action.element_context.model_dump() if action.element_context else None
            ),
            viewport=dict(action.viewport) if action.viewport else None,
        )

    @staticmethod
    def _network_to_row(event: NetworkEvent) -> NetworkEventRow:
        return NetworkEventRow(
            timestamp=event.timestamp,
            method=event.method,
            url=event.url,
            status=event.status,
            request_headers=dict(event.request_headers),
            response_summary=event.response_summary,
        )

    @staticmethod
    def _row_to_recording(row: RecordingRow) -> Recording:
        actions = [RecordingRepository._row_to_action(a) for a in row.actions]
        network = [RecordingRepository._row_to_network(n) for n in row.network_events]
        parameters = {k: ParameterDef.model_validate(v) for k, v in (row.parameters or {}).items()}
        return Recording(
            id=UUID(row.id),
            name=row.name,
            description=row.description,
            created_at=row.created_at,
            created_by=row.created_by,
            starting_url=row.starting_url,
            actions=actions,
            network_log=network,
            parameters=parameters,
            tags=list(row.tags or []),
        )

    @staticmethod
    def _row_to_action(row: RecordedActionRow) -> RecordedAction:
        action_type = ActionType(row.action_type)
        return RecordedAction(
            id=UUID(row.id),
            sequence=row.sequence,
            timestamp=row.timestamp,
            action_type=action_type,
            payload=_payload_from_dict(action_type, row.payload or {}),
            selector=_model_or_none(ElementSelector, row.selector),
            element_context=_model_or_none(ElementContext, row.element_context),
            url=row.url,
            page_title=row.page_title,
            frame_url=row.frame_url,
            viewport=dict(row.viewport) if row.viewport else None,
            semantic_intent=SemanticIntent(row.semantic_intent),
            classification_confidence=row.classification_confidence,
            classification_reasoning=row.classification_reasoning,
            user_confirmed=row.user_confirmed,
            user_label=row.user_label,
            is_parameterized=row.is_parameterized,
            parameter_name=row.parameter_name,
        )

    @staticmethod
    def _row_to_network(row: NetworkEventRow) -> NetworkEvent:
        return NetworkEvent(
            timestamp=row.timestamp,
            method=row.method,
            url=row.url,
            status=row.status,
            request_headers=dict(row.request_headers or {}),
            response_summary=row.response_summary,
        )


class RunResultRepository:
    """CRUD over `RunResult` aggregates (run + executions + attempts)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, run: RunResult) -> None:
        """Insert a new run with all action executions and attempts."""
        row = RunResultRow(
            id=str(run.id),
            recording_id=str(run.recording_id),
            started_at=run.started_at,
            ended_at=run.ended_at,
            status=run.status.value,
            summary=run.summary,
            parameter_values=dict(run.parameter_values),
        )
        for execution in run.executions:
            row.executions.append(self._execution_to_row(execution))
        self._session.add(row)
        await self._session.flush()

    async def get(self, run_id: UUID) -> RunResult | None:
        """Load a run with eager-loaded executions and attempts."""
        stmt = (
            select(RunResultRow)
            .where(RunResultRow.id == str(run_id))
            .options(
                selectinload(RunResultRow.executions).selectinload(ActionExecutionRow.attempts),
            )
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        if row is None:
            return None
        return self._row_to_run(row)

    async def list_for_recording(self, recording_id: UUID) -> list[RunResultSummary]:
        """Summaries of every run that targeted the given recording."""
        stmt = (
            select(
                RunResultRow.id,
                RunResultRow.recording_id,
                RunResultRow.started_at,
                RunResultRow.ended_at,
                RunResultRow.status,
            )
            .where(RunResultRow.recording_id == str(recording_id))
            .order_by(RunResultRow.started_at.desc())
        )
        result = await self._session.execute(stmt)
        return [
            RunResultSummary(
                id=UUID(row.id),
                recording_id=UUID(row.recording_id),
                started_at=row.started_at,
                ended_at=row.ended_at,
                status=ExecutionStatus(row.status),
            )
            for row in result.all()
        ]

    @staticmethod
    def _execution_to_row(execution: ActionExecution) -> ActionExecutionRow:
        row = ActionExecutionRow(
            action_id=str(execution.action_id),
            status=execution.status.value,
            duration_ms=execution.duration_ms,
            recovery=execution.recovery.model_dump() if execution.recovery else None,
        )
        for attempt in execution.attempts:
            row.attempts.append(RunResultRepository._attempt_to_row(attempt))
        return row

    @staticmethod
    def _attempt_to_row(attempt: ExecutionAttempt) -> ExecutionAttemptRow:
        return ExecutionAttemptRow(
            id=str(attempt.id),
            attempt_number=attempt.attempt_number,
            started_at=attempt.started_at,
            ended_at=attempt.ended_at,
            status=attempt.status.value,
            failure_mode=attempt.failure_mode.value if attempt.failure_mode else None,
            error_message=attempt.error_message,
            screenshot_path=attempt.screenshot_path,
            dom_snapshot_path=attempt.dom_snapshot_path,
            accessibility_snapshot_path=attempt.accessibility_snapshot_path,
            selector_used=attempt.selector_used.model_dump() if attempt.selector_used else None,
            console_log=list(attempt.console_log),
            js_errors=list(attempt.js_errors),
        )

    @staticmethod
    def _row_to_run(row: RunResultRow) -> RunResult:
        return RunResult(
            id=UUID(row.id),
            recording_id=UUID(row.recording_id),
            started_at=row.started_at,
            ended_at=row.ended_at,
            status=ExecutionStatus(row.status),
            parameter_values=dict(row.parameter_values or {}),
            executions=[RunResultRepository._row_to_execution(e) for e in row.executions],
            summary=row.summary,
        )

    @staticmethod
    def _row_to_execution(row: ActionExecutionRow) -> ActionExecution:
        return ActionExecution(
            action_id=UUID(row.action_id),
            status=ExecutionStatus(row.status),
            attempts=[RunResultRepository._row_to_attempt(a) for a in row.attempts],
            recovery=_model_or_none(RecoveryAction, row.recovery),
            duration_ms=row.duration_ms,
        )

    @staticmethod
    def _row_to_attempt(row: ExecutionAttemptRow) -> ExecutionAttempt:
        return ExecutionAttempt(
            id=UUID(row.id),
            attempt_number=row.attempt_number,
            started_at=row.started_at,
            ended_at=row.ended_at,
            status=ExecutionStatus(row.status),
            selector_used=_model_or_none(ElementSelector, row.selector_used),
            failure_mode=FailureMode(row.failure_mode) if row.failure_mode else None,
            error_message=row.error_message,
            screenshot_path=row.screenshot_path,
            dom_snapshot_path=row.dom_snapshot_path,
            accessibility_snapshot_path=row.accessibility_snapshot_path,
            console_log=list(row.console_log or []),
            js_errors=list(row.js_errors or []),
        )


class BronzeArtifactRepository:
    """CRUD over `BronzeArtifactRow` pointer rows.

    `BronzeWriter` calls into this to register each artifact it persists. The
    repository methods do not commit on their own — `get_session()` owns
    transaction boundaries.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(
        self,
        *,
        artifact_id: str,
        kind: str,
        path: str,
        sha256: str,
        size_bytes: int,
        recording_id: str | None = None,
        run_id: str | None = None,
        attempt_id: str | None = None,
    ) -> None:
        """Insert a new pointer row. `sha256` and `size_bytes` may be filled in later."""
        row = BronzeArtifactRow(
            id=artifact_id,
            kind=kind,
            path=path,
            sha256=sha256,
            size_bytes=size_bytes,
            recording_id=recording_id,
            run_id=run_id,
            attempt_id=attempt_id,
        )
        self._session.add(row)
        await self._session.flush()

    async def update_size_and_sha(
        self,
        *,
        path: str,
        sha256: str,
        size_bytes: int,
    ) -> None:
        """Backfill `sha256` + `size_bytes` for an artifact registered earlier."""
        stmt = select(BronzeArtifactRow).where(BronzeArtifactRow.path == path)
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        if row is None:
            return
        row.sha256 = sha256
        row.size_bytes = size_bytes
        await self._session.flush()

    async def list_for_recording(self, recording_id: UUID) -> list[BronzeArtifactRow]:
        """Return every pointer row attached to a recording, oldest first."""
        stmt = (
            select(BronzeArtifactRow)
            .where(BronzeArtifactRow.recording_id == str(recording_id))
            .order_by(BronzeArtifactRow.created_at)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_for_attempt(self, attempt_id: UUID) -> list[BronzeArtifactRow]:
        """Return every pointer row attached to one execution attempt."""
        stmt = (
            select(BronzeArtifactRow)
            .where(BronzeArtifactRow.attempt_id == str(attempt_id))
            .order_by(BronzeArtifactRow.created_at)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_all(self) -> list[BronzeArtifactRow]:
        """Return every pointer row, oldest first. Used by retention pruning."""
        stmt = select(BronzeArtifactRow).order_by(BronzeArtifactRow.created_at)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def delete_by_id(self, artifact_id: str) -> None:
        """Idempotent delete by primary key."""
        row = await self._session.get(BronzeArtifactRow, artifact_id)
        if row is not None:
            await self._session.delete(row)
            await self._session.flush()


class GoldHotRepository:
    """Upserts for the hot gold tables (M11.5).

    `recompute_gold_hot(...)` builds rows from silver and pushes them through
    these methods. Idempotent: re-running with the same primary key updates
    the existing row instead of inserting a duplicate.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_recording_metrics(
        self,
        *,
        recording_id: str,
        total_runs: int,
        success_rate: float,
        avg_duration_ms: int,
        classifier_confidence_avg: float,
        last_replayed_at: datetime | None,
        computed_at: datetime,
    ) -> None:
        existing = await self._session.get(GoldRecordingMetricsRow, recording_id)
        if existing is None:
            self._session.add(
                GoldRecordingMetricsRow(
                    recording_id=recording_id,
                    total_runs=total_runs,
                    success_rate=success_rate,
                    avg_duration_ms=avg_duration_ms,
                    classifier_confidence_avg=classifier_confidence_avg,
                    last_replayed_at=last_replayed_at,
                    computed_at=computed_at,
                ),
            )
        else:
            existing.total_runs = total_runs
            existing.success_rate = success_rate
            existing.avg_duration_ms = avg_duration_ms
            existing.classifier_confidence_avg = classifier_confidence_avg
            existing.last_replayed_at = last_replayed_at
            existing.computed_at = computed_at
        await self._session.flush()

    async def upsert_run_dashboard_row(
        self,
        *,
        run_date: Any,
        recording_id: str,
        runs_total: int,
        runs_success: int,
        runs_failed: int,
        runs_recovered: int,
        computed_at: datetime,
    ) -> None:
        stmt = select(GoldRunDashboardRow).where(
            GoldRunDashboardRow.date == run_date,
            GoldRunDashboardRow.recording_id == recording_id,
        )
        existing = (await self._session.execute(stmt)).scalar_one_or_none()
        if existing is None:
            self._session.add(
                GoldRunDashboardRow(
                    date=run_date,
                    recording_id=recording_id,
                    runs_total=runs_total,
                    runs_success=runs_success,
                    runs_failed=runs_failed,
                    runs_recovered=runs_recovered,
                    computed_at=computed_at,
                ),
            )
        else:
            existing.runs_total = runs_total
            existing.runs_success = runs_success
            existing.runs_failed = runs_failed
            existing.runs_recovered = runs_recovered
            existing.computed_at = computed_at
        await self._session.flush()

    async def get_recording_metrics(
        self, recording_id: str
    ) -> GoldRecordingMetricsRow | None:
        return await self._session.get(GoldRecordingMetricsRow, recording_id)

    async def list_dashboard_rows(self) -> list[GoldRunDashboardRow]:
        stmt = select(GoldRunDashboardRow).order_by(
            GoldRunDashboardRow.date,
            GoldRunDashboardRow.recording_id,
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
