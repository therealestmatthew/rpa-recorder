"""Retention enforcement for bronze artifacts (M11.5).

Walks every `bronze_artifacts` row, deletes those older than their kind's
window from the store and from the table. `dry_run=True` reports what
would be deleted without acting.

Windows are per-kind so noisy artifacts (failure screenshots) age out
fast while audit-grade content (LLM call dumps, raw events) stays
longer. Unknown kinds keep forever — better to keep too much than to
silently lose evidence.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from rpa_recorder.medallion.bronze_store import BronzeStore
    from rpa_recorder.storage.repositories import BronzeArtifactRepository

_log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class RetentionConfig:
    """Per-kind retention windows in days. Zero or absent = keep forever."""

    windows_by_kind: dict[str, int]


@dataclass
class RetentionReport:
    """Outcome of one retention pass."""

    deleted_paths: list[str]
    skipped_paths: list[str]
    failed_paths: list[tuple[str, str]]
    dry_run: bool

    @property
    def deleted_count(self) -> int:
        return len(self.deleted_paths)


async def enforce_retention(
    bronze_store: BronzeStore,
    bronze_repo: BronzeArtifactRepository,
    config: RetentionConfig,
    *,
    dry_run: bool = False,
    now: datetime | None = None,
) -> RetentionReport:
    """Delete artifacts older than their kind's window. Returns a report.

    `now` is injectable for tests; production passes `None` and we
    snapshot wall-clock once at entry so iteration is consistent across
    rows even on slow runs.
    """
    cutoff_now = now or datetime.now(UTC)

    deleted: list[str] = []
    skipped: list[str] = []
    failed: list[tuple[str, str]] = []

    rows = await bronze_repo.list_all()
    for row in rows:
        window_days = config.windows_by_kind.get(row.kind, 0)
        if window_days <= 0:
            skipped.append(row.path)
            continue
        cutoff = cutoff_now - timedelta(days=window_days)
        created = row.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        if created >= cutoff:
            skipped.append(row.path)
            continue

        if dry_run:
            deleted.append(row.path)
            continue

        try:
            await bronze_store.delete(row.path)
        except OSError as exc:
            failed.append((row.path, str(exc)))
            _log.warning(
                "retention_store_delete_failed",
                path=row.path,
                error=str(exc),
            )
            continue
        try:
            await bronze_repo.delete_by_id(row.id)
        except Exception as exc:
            failed.append((row.path, str(exc)))
            _log.warning(
                "retention_repo_delete_failed",
                path=row.path,
                error=str(exc),
            )
            continue
        deleted.append(row.path)

    return RetentionReport(
        deleted_paths=deleted,
        skipped_paths=skipped,
        failed_paths=failed,
        dry_run=dry_run,
    )


__all__ = ["RetentionConfig", "RetentionReport", "enforce_retention"]
