"""`rpa medallion <subcommand>` — operator surface for medallion ops.

Sub-Typer with: `promote`, `compact`, `prune`, `status`. Each subcommand
runs the M11.5 job in-process (no ARQ worker required) so operators can
trigger one-offs without a running worker process.
"""

from uuid import UUID

import typer

from rpa_recorder.cli.app import app
from rpa_recorder.cli.async_runner import run_async
from rpa_recorder.cli.errors import handle_cli_errors

medallion_app = typer.Typer(
    name="medallion",
    help="Medallion silver/gold operations: promote, compact, prune, status.",
    no_args_is_help=True,
)
app.add_typer(medallion_app)


@medallion_app.command("promote")
@handle_cli_errors
def promote(
    layer: str = typer.Option(
        "gold",
        "--layer",
        help="'silver' (bronze JSONL -> RecordedActionRow) or 'gold' (silver -> gold).",
    ),
    recording: str | None = typer.Option(
        None,
        "--recording",
        help="Optional UUID. For silver, required. For gold, defaults to all.",
    ),
) -> None:
    """Promote bronze->silver or silver->gold."""
    if layer == "silver":
        if recording is None:
            raise typer.BadParameter("`--recording` required for silver", param_hint="--recording")
        run_async(_promote_silver)(UUID(recording))
    elif layer == "gold":
        rec_id = UUID(recording) if recording else None
        run_async(_promote_gold)(rec_id)
    else:
        raise typer.BadParameter(
            f"unknown layer {layer!r}; expected 'silver' or 'gold'",
            param_hint="--layer",
        )


@medallion_app.command("compact")
@handle_cli_errors
def compact() -> None:
    """Compact every recording's bronze JSONL into Parquet (idempotent)."""
    run_async(_compact_all)()


@medallion_app.command("prune")
@handle_cli_errors
def prune(
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Report what would be deleted without acting."
    ),
) -> None:
    """Enforce retention windows on bronze artifacts."""
    run_async(_prune)(dry_run=dry_run)


@medallion_app.command("status")
@handle_cli_errors
def status() -> None:
    """Show artifact counts by `kind` and parquet table sizes."""
    run_async(_status)()


# ----- async bodies ----------------------------------------------------------


async def _promote_silver(recording_id: UUID) -> None:
    from rpa_recorder.config import Config  # noqa: PLC0415
    from rpa_recorder.medallion.bronze_store import LocalFilesystemStore  # noqa: PLC0415
    from rpa_recorder.medallion.silver import promote_bronze_to_silver  # noqa: PLC0415
    from rpa_recorder.storage.db import create_engine, get_session, init_db  # noqa: PLC0415

    config = Config()
    engine = create_engine(config.database_url)
    await init_db(engine)
    store = LocalFilesystemStore(config.bronze_root)
    try:
        async with get_session(engine) as db:
            inserted = await promote_bronze_to_silver(db, store, recording_id)
        typer.echo(f"silver: inserted {inserted} rows for {recording_id}")
    finally:
        await engine.dispose()


async def _promote_gold(recording_id: UUID | None) -> None:
    from rpa_recorder.config import Config  # noqa: PLC0415
    from rpa_recorder.medallion.gold_cold import ColdGold  # noqa: PLC0415
    from rpa_recorder.medallion.gold_hot import recompute_gold_hot  # noqa: PLC0415
    from rpa_recorder.storage.db import create_engine, get_session, init_db  # noqa: PLC0415

    config = Config()
    engine = create_engine(config.database_url)
    await init_db(engine)
    cold = ColdGold(config.gold_cold_root)
    try:
        async with get_session(engine) as db:
            upserts = await recompute_gold_hot(db, recording_id=recording_id)
        async with get_session(engine) as db:
            await cold.recompute_classifier_accuracy(db)
            await cold.recompute_llm_costs_daily(db)
            await cold.recompute_training_data(db)
            if recording_id is not None:
                await cold.recompute_replay_scripts(db, recording_id)
        typer.echo(f"gold: {upserts} hot upserts; cold parquet refreshed")
    finally:
        await engine.dispose()


async def _compact_all() -> None:
    from rpa_recorder.config import Config  # noqa: PLC0415
    from rpa_recorder.medallion.bronze_store import LocalFilesystemStore  # noqa: PLC0415
    from rpa_recorder.medallion.compact import compact_all_recordings  # noqa: PLC0415
    from rpa_recorder.storage.db import create_engine, get_session, init_db  # noqa: PLC0415
    from rpa_recorder.storage.repositories import BronzeArtifactRepository  # noqa: PLC0415

    config = Config()
    engine = create_engine(config.database_url)
    await init_db(engine)
    store = LocalFilesystemStore(config.bronze_root)
    try:
        async with get_session(engine) as db:
            repo = BronzeArtifactRepository(db)
            written = await compact_all_recordings(
                store, repo, parquet_root=config.bronze_root,
            )
        typer.echo(f"compact: wrote {len(written)} parquet files")
        for path in written:
            typer.echo(f"  - {path}")
    finally:
        await engine.dispose()


async def _prune(*, dry_run: bool) -> None:
    from rpa_recorder.config import Config  # noqa: PLC0415
    from rpa_recorder.medallion.bronze_store import LocalFilesystemStore  # noqa: PLC0415
    from rpa_recorder.medallion.retention import (  # noqa: PLC0415
        RetentionConfig,
        enforce_retention,
    )
    from rpa_recorder.storage.db import create_engine, get_session, init_db  # noqa: PLC0415
    from rpa_recorder.storage.repositories import BronzeArtifactRepository  # noqa: PLC0415
    from rpa_recorder.workers.jobs.prune import _windows_from_config  # noqa: PLC0415

    config = Config()
    engine = create_engine(config.database_url)
    await init_db(engine)
    store = LocalFilesystemStore(config.bronze_root)
    retention = RetentionConfig(windows_by_kind=_windows_from_config(config))
    try:
        async with get_session(engine) as db:
            repo = BronzeArtifactRepository(db)
            report = await enforce_retention(store, repo, retention, dry_run=dry_run)
        action = "would delete" if dry_run else "deleted"
        typer.echo(
            f"prune: {action} {report.deleted_count}; "
            f"skipped {len(report.skipped_paths)}; failed {len(report.failed_paths)}"
        )
    finally:
        await engine.dispose()


async def _status() -> None:
    from collections import Counter  # noqa: PLC0415

    from rpa_recorder.config import Config  # noqa: PLC0415
    from rpa_recorder.storage.db import create_engine, get_session, init_db  # noqa: PLC0415
    from rpa_recorder.storage.repositories import BronzeArtifactRepository  # noqa: PLC0415

    config = Config()
    engine = create_engine(config.database_url)
    await init_db(engine)
    try:
        async with get_session(engine) as db:
            rows = await BronzeArtifactRepository(db).list_all()
        counts: Counter[str] = Counter(r.kind for r in rows)
        typer.echo("bronze artifacts by kind:")
        for kind, count in sorted(counts.items()):
            typer.echo(f"  {kind:24} {count}")
        typer.echo(f"gold cold root: {config.gold_cold_root}")
    finally:
        await engine.dispose()
