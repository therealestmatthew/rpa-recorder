"""Medallion data architecture: bronze (raw), silver (validated), gold (analytics).

Bronze (M6.5): `BronzeStore` Protocol + `LocalFilesystemStore` + `BronzeWriter`
routes raw recorder envelopes, failure artifacts, HAR/trace bundles, LLM
calls, and confirmation audit logs into the store and registers pointer rows
in `bronze_artifacts`.

Silver/Gold (M11.5): `silver.py` re-derives `RecordedActionRow` from bronze
JSONL on demand. `gold_hot.py` upserts `gold_recording_metrics` and
`gold_run_dashboard` from silver. `gold_cold.py` writes DuckDB-readable
Parquet under `data/gold/cold/`. `compact.py` rolls bronze JSONL into
Parquet on a 15-min cadence. `retention.py` ages out artifacts per-kind.
"""

from rpa_recorder.medallion import paths
from rpa_recorder.medallion.bronze import BronzeWriter
from rpa_recorder.medallion.bronze_store import BronzeStore, LocalFilesystemStore
from rpa_recorder.medallion.compact import (
    compact_all_recordings,
    compact_recording_jsonl_to_parquet,
)
from rpa_recorder.medallion.gold_cold import ColdGold
from rpa_recorder.medallion.gold_hot import recompute_gold_hot
from rpa_recorder.medallion.retention import (
    RetentionConfig,
    RetentionReport,
    enforce_retention,
)
from rpa_recorder.medallion.silver import promote_bronze_to_silver

__all__ = [
    "BronzeStore",
    "BronzeWriter",
    "ColdGold",
    "LocalFilesystemStore",
    "RetentionConfig",
    "RetentionReport",
    "compact_all_recordings",
    "compact_recording_jsonl_to_parquet",
    "enforce_retention",
    "paths",
    "promote_bronze_to_silver",
    "recompute_gold_hot",
]
