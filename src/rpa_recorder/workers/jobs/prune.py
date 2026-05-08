"""ARQ `prune_old_artifacts` cron job (daily at 03:00 UTC)."""

from typing import Any

import structlog

_log = structlog.get_logger(__name__)


def _windows_from_config(config: Any) -> dict[str, int]:
    """Derive per-kind retention day-windows from the config."""
    return {
        "raw_events_jsonl": int(config.bronze_retention_jsonl_days),
        "event_parquet": int(config.bronze_retention_parquet_days),
        "har": int(config.bronze_retention_har_days),
        "trace": int(config.bronze_retention_trace_days),
        "attempt_screenshot": int(config.bronze_retention_failure_days),
        "attempt_dom": int(config.bronze_retention_failure_days),
        "attempt_a11y": int(config.bronze_retention_failure_days),
        "llm_call": int(config.bronze_retention_llm_days),
    }


async def prune_old_artifacts(
    ctx: dict[str, Any], *, dry_run: bool = False
) -> dict[str, Any]:
    """Delete bronze artifacts older than their kind's retention window."""
    from rpa_recorder.config import Config  # noqa: PLC0415
    from rpa_recorder.medallion.retention import (  # noqa: PLC0415
        RetentionConfig,
        enforce_retention,
    )
    from rpa_recorder.storage.db import get_session  # noqa: PLC0415
    from rpa_recorder.storage.repositories import BronzeArtifactRepository  # noqa: PLC0415

    engine = ctx["db_engine"]
    bronze_store = ctx["bronze_store"]
    config: Config = ctx.get("config") or Config()
    log = _log.bind(job_id=ctx.get("job_id"))

    retention = RetentionConfig(windows_by_kind=_windows_from_config(config))

    async with get_session(engine) as db:
        repo = BronzeArtifactRepository(db)
        report = await enforce_retention(
            bronze_store, repo, retention, dry_run=dry_run
        )

    log.info(
        "prune_complete",
        deleted=report.deleted_count,
        skipped=len(report.skipped_paths),
        failed=len(report.failed_paths),
        dry_run=dry_run,
    )
    return {
        "status": "ok",
        "deleted": report.deleted_paths,
        "skipped_count": len(report.skipped_paths),
        "failed_count": len(report.failed_paths),
        "dry_run": dry_run,
    }
