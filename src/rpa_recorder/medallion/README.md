# medallion

Three-tier data layout: bronze (raw artifacts) → silver (validated rows in
[`storage/`](../storage/)) → gold (analytics shapes for dashboards and
training data). See [ADR-0001](../../../.claude/plans/adr/0001-medallion-bronze-silver-gold-split.md)
for rationale.

## Layout

```
medallion/
├── __init__.py
├── paths.py            # filesystem layout: data/{bronze,silver,gold}/...
├── bronze.py           # BronzeWriter: append JSONL, write screenshots/DOM/HAR/LLM blobs
├── bronze_store.py     # BronzeStore Protocol + LocalFilesystemStore impl
├── silver.py           # silver promotion (bronze JSONL → typed silver rows)
├── gold_hot.py         # SQLite-backed dashboard aggregates
├── gold_cold.py        # DuckDB-on-Parquet long-form training data
├── compact.py          # JSONL → Parquet compaction (hourly cron)
└── retention.py        # prune_old_bronze (nightly cron)
```

## Conventions

- **Bronze is append-only and operator-private.** Raw values (including
  `is_sensitive=True` payloads) are preserved here for replay debugging.
  Redaction happens at the silver/gold boundary and at the LLM-prompt
  boundary in [`classifier/llm/`](../classifier/).
- **Filesystem layout is owned by `paths.py`.** Don't construct paths
  ad-hoc; route through `paths.bronze_dir(recording_id)` etc. The
  `BronzeStore` Protocol shields callers from "is this S3 or disk?"
  questions in case we add a remote store later.
- **`bronze_artifacts` rows are the silver-side index.** Every blob
  written to bronze gets a row in the `bronze_artifacts` table (path,
  type, size, sha256). Silver promotion reads those rows; never scans
  the filesystem at promotion time.
- **Promotions are idempotent.** `silver.py`, `gold_hot.py`, and
  `gold_cold.py` use upsert / replace semantics keyed on stable IDs.
  Re-running a promotion is safe and a no-op when no new rows exist.
- **Retention windows are configurable.** `RPA_BRONZE_RETENTION_JSONL_DAYS`
  (default 30) controls hot JSONL retention; Parquet compaction preserves
  data beyond that horizon. See
  [`docs/m11.5-workers-and-medallion-promotion.md`](../../../docs/m11.5-workers-and-medallion-promotion.md).

## Adding a gold table

1. Decide hot or cold:
   - **Hot** = small, frequently queried, lives in SQLite; add to
     `gold_hot.py` with a SQLAlchemy table and a `promote_to_<name>` fn.
   - **Cold** = large or analytical, lives in Parquet under
     `data/gold/cold/<name>/`; add to `gold_cold.py` with a DuckDB
     INSERT SELECT.
2. Wire the promotion fn into the `promote_silver_to_gold` job in
   [`workers/`](../workers/).
3. Add an entry to [`docs/configuration.md`](../../../docs/configuration.md)
   if it introduces new env vars.

## See also

- [ADR-0001](../../../.claude/plans/adr/0001-medallion-bronze-silver-gold-split.md) — three-tier rationale.
- [`docs/m6.5-page-scripts-and-bronze.md`](../../../docs/m6.5-page-scripts-and-bronze.md) — bronze layer milestone.
- [`docs/m11.5-workers-and-medallion-promotion.md`](../../../docs/m11.5-workers-and-medallion-promotion.md) — silver/gold promotion milestone.
- [`docs/medallion-and-workers.md`](../../../docs/medallion-and-workers.md) — full data-flow reference.
- [`workers/README.md`](../workers/README.md) — cron jobs that drive promotion + retention.
