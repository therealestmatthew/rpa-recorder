"""ARQ job registry. Each job is `async def fn(ctx, *, ...)` per ARQ contract."""

from rpa_recorder.workers.jobs.bronze_compact import compact_bronze_to_parquet
from rpa_recorder.workers.jobs.classify import classify_recording
from rpa_recorder.workers.jobs.medallion import (
    promote_bronze_to_silver,
    promote_silver_to_gold,
)
from rpa_recorder.workers.jobs.prune import prune_old_artifacts
from rpa_recorder.workers.jobs.replay import replay_run
from rpa_recorder.workers.jobs.summary import generate_run_summary

__all__ = [
    "classify_recording",
    "compact_bronze_to_parquet",
    "generate_run_summary",
    "promote_bronze_to_silver",
    "promote_silver_to_gold",
    "prune_old_artifacts",
    "replay_run",
]
