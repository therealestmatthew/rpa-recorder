"""`rpa confirm <id>` — interactive review of classified actions (M11)."""

from contextlib import AsyncExitStack
from datetime import datetime  # noqa: TC003 — Typer reads annotations at runtime
from typing import TYPE_CHECKING, Any
from uuid import UUID

import typer
from sqlalchemy import select

from rpa_recorder.cli.app import app
from rpa_recorder.cli.async_runner import run_async
from rpa_recorder.cli.dependencies import (
    SessionFactory,
    init_database,
    make_bronze_writer_factory,
    make_session_factory,
)
from rpa_recorder.cli.errors import CLIError, handle_cli_errors
from rpa_recorder.models import SemanticIntent
from rpa_recorder.storage.db import (
    ActionExecutionRow,
    ExecutionAttemptRow,
    RunResultRow,
)

if TYPE_CHECKING:
    from rpa_recorder.medallion import BronzeWriter


@app.command(name="confirm")
@handle_cli_errors
def confirm(
    recording_id: str = typer.Argument(..., help="UUID of the recording to review."),
    threshold: float = typer.Option(
        0.7, "--threshold", "-t", help="Confidence cutoff for the default filter."
    ),
    filter_name: str | None = typer.Option(
        None, "--filter", "-f", help="Filter to use; defaults to Config setting."
    ),
    mode_name: str | None = typer.Option(
        None, "--mode", "-m", help="Review mode; defaults to Config setting."
    ),
    renderer_name: str | None = typer.Option(
        None, "--renderer", "-r", help="Renderer; defaults to Config setting."
    ),
    intent: str | None = typer.Option(None, "--intent", help="Required by --filter by_intent."),
    since: datetime | None = typer.Option(
        None, "--since", help="ISO timestamp; required by --filter since_date."
    ),
    baseline: datetime | None = typer.Option(
        None,
        "--baseline",
        help="ISO timestamp; used by --mode diff_baseline.",
    ),
    audit_bronze: bool = typer.Option(
        True,
        "--audit-bronze/--no-audit-bronze",
        help="Append a bronze decisions.jsonl per recording.",
    ),
) -> None:
    """Walk a recording's actions and accept / relabel / skip each."""
    run_async(_confirm_async)(
        recording_id=recording_id,
        threshold=threshold,
        filter_name=filter_name,
        mode_name=mode_name,
        renderer_name=renderer_name,
        intent=intent,
        since=since,
        baseline=baseline,
        audit_bronze=audit_bronze,
    )


async def _confirm_async(
    *,
    recording_id: str,
    threshold: float,
    filter_name: str | None,
    mode_name: str | None,
    renderer_name: str | None,
    intent: str | None,
    since: datetime | None,
    baseline: datetime | None,
    audit_bronze: bool,
) -> None:
    try:
        rec_uuid = UUID(recording_id)
    except ValueError as exc:
        raise CLIError(f"invalid UUID: {recording_id!r}") from exc

    await init_database()
    session_factory = make_session_factory()

    filter_kwargs = await _build_filter_kwargs(
        filter_name=filter_name,
        intent=intent,
        since=since,
        rec_uuid=rec_uuid,
        session_factory=session_factory,
    )
    mode_kwargs = _build_mode_kwargs(mode_name=mode_name, baseline=baseline)

    # Lazy import to break the cli ↔ confirmation cycle introduced when
    # modes import `rpa_recorder.cli.console` at module load time.
    from rpa_recorder.confirmation import default_runner  # noqa: PLC0415

    async with AsyncExitStack() as stack:
        bronze_writer: BronzeWriter | None = None
        if audit_bronze:
            bronze_session = await stack.enter_async_context(session_factory())
            bronze_writer = make_bronze_writer_factory()(bronze_session)

        runner = default_runner(
            session_factory=session_factory,
            threshold=threshold,
            bronze_writer=bronze_writer,
            filter_name=filter_name,
            filter_kwargs=filter_kwargs,
            mode_name=mode_name,
            mode_kwargs=mode_kwargs,
            renderer_name=renderer_name,
        )
        try:
            await runner.run(rec_uuid)
        except LookupError as exc:
            raise CLIError(str(exc)) from exc


async def _build_filter_kwargs(
    *,
    filter_name: str | None,
    intent: str | None,
    since: datetime | None,
    rec_uuid: UUID,
    session_factory: SessionFactory,
) -> dict[str, Any]:
    if filter_name == "by_intent":
        if intent is None:
            msg = "--intent is required with --filter by_intent"
            raise CLIError(msg)
        try:
            return {"intent": SemanticIntent(intent)}
        except ValueError as exc:
            raise CLIError(f"unknown intent: {intent!r}") from exc
    if filter_name == "since_date":
        if since is None:
            msg = "--since is required with --filter since_date"
            raise CLIError(msg)
        return {"cutoff": since}
    if filter_name == "failed_on_replay":
        ids = await _fetch_failed_action_ids(rec_uuid, session_factory)
        return {"failed_action_ids": ids}
    return {}


def _build_mode_kwargs(*, mode_name: str | None, baseline: datetime | None) -> dict[str, Any]:
    if mode_name == "diff_baseline":
        if baseline is None:
            msg = "--baseline is required with --mode diff_baseline"
            raise CLIError(msg)
        return {"baseline_at": baseline}
    return {}


async def _fetch_failed_action_ids(rec_uuid: UUID, session_factory: SessionFactory) -> list[UUID]:
    async with session_factory() as db:
        stmt = (
            select(ActionExecutionRow.action_id)
            .join(RunResultRow, RunResultRow.id == ActionExecutionRow.run_id)
            .join(
                ExecutionAttemptRow,
                ExecutionAttemptRow.action_execution_id == ActionExecutionRow.id,
            )
            .where(RunResultRow.recording_id == str(rec_uuid))
            .where(ExecutionAttemptRow.status != "success")
        )
        rows = (await db.execute(stmt)).scalars().all()
    return [UUID(r) for r in set(rows)]
