"""Async SQLAlchemy 2.0 engine, declarative base, table definitions, sessions.

The schema mirrors the persisted shape laid out in `.claude/plans/data-capture.md`:
typed columns for queryable fields, JSON columns for nested Pydantic structures,
UUID primary keys stored as `String(36)` for SQLite portability. Repositories in
`storage/repositories.py` adapt these rows to and from the Pydantic models.
"""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from datetime import date as date_
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    event,
)
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


class Base(DeclarativeBase):
    """Common declarative base shared by every ORM table."""


def _new_uuid() -> str:
    """Generate a fresh string-typed UUID for primary keys."""
    return str(uuid4())


class RecordingRow(Base):
    """`recordings` table: top-level recorded workflows."""

    __tablename__ = "recordings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    starting_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)

    actions: Mapped[list[RecordedActionRow]] = relationship(
        back_populates="recording",
        cascade="all, delete-orphan",
        order_by="RecordedActionRow.sequence",
    )
    network_events: Mapped[list[NetworkEventRow]] = relationship(
        back_populates="recording",
        cascade="all, delete-orphan",
        order_by="NetworkEventRow.timestamp",
    )


class RecordedActionRow(Base):
    """`recorded_actions` table: one row per captured user action."""

    __tablename__ = "recorded_actions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    recording_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("recordings.id", ondelete="CASCADE"),
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    action_type: Mapped[str] = mapped_column(String(32), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    page_title: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    frame_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    semantic_intent: Mapped[str] = mapped_column(String(64), nullable=False, default="unknown")
    classification_confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    classification_reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    user_label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_parameterized: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    parameter_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    selector: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    element_context: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    viewport: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    recording: Mapped[RecordingRow] = relationship(back_populates="actions")


class NetworkEventRow(Base):
    """`network_events` table: lightweight HTTP request/response metadata."""

    __tablename__ = "network_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    recording_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("recordings.id", ondelete="CASCADE"),
        nullable=False,
    )
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    method: Mapped[str] = mapped_column(String(16), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    request_headers: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    response_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    recording: Mapped[RecordingRow] = relationship(back_populates="network_events")


class RunResultRow(Base):
    """`run_results` table: top-level outcome of replaying a recording."""

    __tablename__ = "run_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    recording_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("recordings.id", ondelete="CASCADE"),
        nullable=False,
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    parameter_values: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    executions: Mapped[list[ActionExecutionRow]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
    )


class ActionExecutionRow(Base):
    """`action_executions` table: per-action outcome within a run."""

    __tablename__ = "action_executions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("run_results.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Logical reference to recorded_actions.id; not enforced because run history
    # should survive recording mutations.
    action_id: Mapped[str] = mapped_column(String(36), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recovery: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    run: Mapped[RunResultRow] = relationship(back_populates="executions")
    attempts: Mapped[list[ExecutionAttemptRow]] = relationship(
        back_populates="action_execution",
        cascade="all, delete-orphan",
        order_by="ExecutionAttemptRow.attempt_number",
    )


class ExecutionAttemptRow(Base):
    """`execution_attempts` table: per-try detail under an action_execution."""

    __tablename__ = "execution_attempts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    action_execution_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("action_executions.id", ondelete="CASCADE"),
        nullable=False,
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    failure_mode: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    screenshot_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    dom_snapshot_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    accessibility_snapshot_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    selector_used: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    console_log: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    js_errors: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)

    action_execution: Mapped[ActionExecutionRow] = relationship(back_populates="attempts")


class LLMCallRow(Base):
    """`llm_calls` table: audit log of every Anthropic SDK invocation."""

    __tablename__ = "llm_calls"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    called_for: Mapped[str] = mapped_column(String(16), nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    response: Mapped[str] = mapped_column(Text, nullable=False)
    recording_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    action_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class BronzeArtifactRow(Base):
    """`bronze_artifacts` table: backend-agnostic pointers to bronze-tier files.

    Each row points at one file in the bronze store (`raw_events.jsonl`, a
    HAR, a screenshot, etc.). Optional FKs let queries roll bronze artifacts
    up to a recording, run, or attempt without scanning the file tree.

    The path is store-relative (forward slashes, no backend prefix); the
    backend joins it under its own root.
    """

    __tablename__ = "bronze_artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    path: Mapped[str] = mapped_column(String(2048), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    recording_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("recordings.id", ondelete="SET NULL"),
        nullable=True,
    )
    run_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("run_results.id", ondelete="SET NULL"),
        nullable=True,
    )
    attempt_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("execution_attempts.id", ondelete="SET NULL"),
        nullable=True,
    )


class GoldRecordingMetricsRow(Base):
    """`gold_recording_metrics` table: per-recording aggregate metrics (M11.5).

    Recomputed by `recompute_gold_hot(...)`. Hourly cron + on-demand from
    M11 confirmation flow. Idempotent via primary-key upsert.
    """

    __tablename__ = "gold_recording_metrics"

    recording_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("recordings.id", ondelete="CASCADE"),
        primary_key=True,
    )
    total_runs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    success_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    avg_duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    classifier_confidence_avg: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    last_replayed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )


class GoldRunDashboardRow(Base):
    """`gold_run_dashboard` table: per-day-per-recording roll-up (M11.5).

    Populated by `recompute_gold_hot(...)`. Composite PK lets a query select
    a date range without scanning the whole table. Idempotent: a re-run for
    the same `(date, recording_id)` upserts the counts.
    """

    __tablename__ = "gold_run_dashboard"

    date: Mapped[date_] = mapped_column(Date, nullable=False)
    recording_id: Mapped[str] = mapped_column(String(36), nullable=False)
    runs_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    runs_success: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    runs_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    runs_recovered: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    __table_args__ = (PrimaryKeyConstraint("date", "recording_id"),)


def _set_sqlite_pragmas(dbapi_connection: Any, _connection_record: Any) -> None:
    """Apply WAL + busy_timeout to every SQLite connection.

    Why: M11.5 introduces multi-worker write contention. Without WAL, SQLite
    serializes everything on a single global writer. busy_timeout=5000 makes
    brief contention wait instead of raising `database is locked`.
    """
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
    finally:
        cursor.close()


def create_engine(database_url: str, *, echo: bool = False) -> AsyncEngine:
    """Construct an `AsyncEngine` with project defaults (no pooling tweaks)."""
    engine = create_async_engine(database_url, echo=echo, future=True)
    if database_url.startswith("sqlite"):
        event.listen(engine.sync_engine, "connect", _set_sqlite_pragmas)
    return engine


async def init_db(engine: AsyncEngine) -> None:
    """Create every declared table on the given engine."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@asynccontextmanager
async def get_session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Yield a session that auto-commits on success, rolls back on exception."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
