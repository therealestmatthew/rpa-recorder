"""Medallion data architecture: bronze (raw), silver (validated), gold (analytics).

This package owns the bronze layer in M6.5: a `BronzeStore` Protocol with a
local-filesystem implementation, and a `BronzeWriter` that routes raw recorder
envelopes, executor failure artifacts, HAR/trace bundles, and LLM call dumps
into the store while registering pointer rows in the `bronze_artifacts` table.

Silver promotion + gold (hot SQLite + cold Parquet/DuckDB) land in M11.5.
"""

from rpa_recorder.medallion import paths
from rpa_recorder.medallion.bronze import BronzeWriter
from rpa_recorder.medallion.bronze_store import BronzeStore, LocalFilesystemStore

__all__ = ["BronzeStore", "BronzeWriter", "LocalFilesystemStore", "paths"]
