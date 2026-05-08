"""Smoke checks on the ARQ WorkerSettings classes."""

import pytest

from rpa_recorder.workers.settings import (
    MedallionWorkerSettings,
    ReplayWorkerSettings,
    WorkerSettings,
)


def test_settings_classes_subclass_base() -> None:
    assert issubclass(ReplayWorkerSettings, WorkerSettings)
    assert issubclass(MedallionWorkerSettings, WorkerSettings)


def test_replay_queue_caps_concurrency() -> None:
    """Replay queue is heavyweight — max_jobs must stay tight."""
    assert ReplayWorkerSettings.queue_name == "replay_queue"
    assert ReplayWorkerSettings.max_jobs == 2


def test_medallion_queue_fans_out() -> None:
    """Medallion queue is IO-bound — higher concurrency."""
    assert MedallionWorkerSettings.queue_name == "medallion_queue"
    assert MedallionWorkerSettings.max_jobs == 10


def test_functions_list_covers_all_seven_jobs() -> None:
    names = {f.__name__ for f in WorkerSettings.functions}
    assert names == {
        "replay_run",
        "classify_recording",
        "generate_run_summary",
        "promote_bronze_to_silver",
        "promote_silver_to_gold",
        "compact_bronze_to_parquet",
        "prune_old_artifacts",
    }


def test_cron_jobs_have_non_empty_schedules() -> None:
    """Each cron entry's `minute` set must be non-empty (otherwise it never fires)."""
    assert len(WorkerSettings.cron_jobs) >= 3
    for job in WorkerSettings.cron_jobs:
        minute = getattr(job, "minute", None)
        assert minute is not None
        assert len(minute) >= 1


@pytest.mark.parametrize(
    "attr",
    ["redis_settings", "shutdown_timeout", "keep_result", "job_timeout"],
)
def test_required_attrs_present(attr: str) -> None:
    assert hasattr(WorkerSettings, attr)
