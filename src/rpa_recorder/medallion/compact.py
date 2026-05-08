"""Bronze JSONL → Parquet compaction (M11.5).

Long-running recordings accumulate hot append-only JSONL. Cold storage
(DuckDB queries, archival reads) is much faster against Parquet. This
module compacts each recording's `raw_events.jsonl` into a sibling
`raw_events.parquet` and registers a `bronze_artifacts` row for it.

Idempotent: a recording with an existing `event_parquet` artifact whose
size matches the current JSONL line count is skipped. Atomic writes
(temp file + rename) come from `BronzeStore.put`.

Schema is intentionally flexible: a few extracted columns plus the full
envelope as JSON. A `schema_version` column lets readers filter by
generation when the schema evolves. We avoid lifting a strict schema
from `RecordedAction` because bronze envelopes are raw page-side events
that don't always match the normalized model.
"""

import asyncio
import json
import re
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import pyarrow as pa
import pyarrow.parquet as pq
import structlog

from rpa_recorder.medallion import paths

if TYPE_CHECKING:
    from rpa_recorder.medallion.bronze_store import BronzeStore
    from rpa_recorder.storage.repositories import BronzeArtifactRepository

_log = structlog.get_logger(__name__)

_SCHEMA_VERSION = 1

_ARROW_SCHEMA = pa.schema([
    pa.field("recording_id", pa.string(), nullable=False),
    pa.field("sequence", pa.int64(), nullable=False),
    pa.field("event_type", pa.string(), nullable=True),
    pa.field("timestamp_ms", pa.int64(), nullable=True),
    pa.field("frame_url", pa.string(), nullable=True),
    pa.field("url", pa.string(), nullable=True),
    pa.field("envelope_json", pa.string(), nullable=False),
    pa.field("schema_version", pa.int8(), nullable=False),
])

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def _envelope_to_columns(envelope: dict[str, Any]) -> dict[str, Any]:
    ts = envelope.get("timestamp_ms")
    return {
        "event_type": envelope.get("event_type") if isinstance(envelope.get("event_type"), str) else None,
        "timestamp_ms": int(ts) if isinstance(ts, int | float) and not isinstance(ts, bool) else None,
        "frame_url": envelope.get("frame_url") if isinstance(envelope.get("frame_url"), str) else None,
        "url": envelope.get("url") if isinstance(envelope.get("url"), str) else None,
        "envelope_json": json.dumps(envelope, default=str),
    }


def _build_table(recording_id: str, envelopes: list[dict[str, Any]]) -> pa.Table:
    cols: dict[str, list[Any]] = {
        "recording_id": [],
        "sequence": [],
        "event_type": [],
        "timestamp_ms": [],
        "frame_url": [],
        "url": [],
        "envelope_json": [],
        "schema_version": [],
    }
    for sequence, envelope in enumerate(envelopes):
        extracted = _envelope_to_columns(envelope)
        cols["recording_id"].append(recording_id)
        cols["sequence"].append(sequence)
        cols["event_type"].append(extracted["event_type"])
        cols["timestamp_ms"].append(extracted["timestamp_ms"])
        cols["frame_url"].append(extracted["frame_url"])
        cols["url"].append(extracted["url"])
        cols["envelope_json"].append(extracted["envelope_json"])
        cols["schema_version"].append(_SCHEMA_VERSION)
    return pa.Table.from_pydict(cols, schema=_ARROW_SCHEMA)


def _write_parquet_sync(table: pa.Table, target: Path) -> int:
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix="rpa_compact_",
        suffix=".parquet",
        dir=target.parent,
        delete=False,
    ) as tmp:
        tmp_path = Path(tmp.name)
    try:
        pq.write_table(table, tmp_path, compression="snappy")  # type: ignore[no-untyped-call]
        size = tmp_path.stat().st_size
        tmp_path.replace(target)
        return size
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


async def compact_recording_jsonl_to_parquet(
    bronze_store: BronzeStore,
    bronze_repo: BronzeArtifactRepository,
    recording_id: UUID,
    *,
    parquet_root: Path,
) -> str | None:
    """Compact one recording. Returns the store-relative Parquet path.

    `parquet_root` is the on-disk root for the bronze store
    (`LocalFilesystemStore._root`). DuckDB-on-Parquet querying needs an
    absolute filesystem path, so we both register a store-relative
    pointer in `bronze_artifacts` AND write the file directly through
    pyarrow (bypassing the store's `put` write path so we can use
    pyarrow's columnar writer).

    Returns `None` if the recording has no JSONL or is already compact.
    """
    rec_id_str = str(recording_id)
    jsonl_path = paths.recording_events_jsonl(recording_id)
    parquet_rel = paths.recording_events_parquet(recording_id)

    try:
        raw_bytes = await bronze_store.get(jsonl_path)
    except FileNotFoundError:
        return None

    text = raw_bytes.decode("utf-8")
    envelopes: list[dict[str, Any]] = []
    for line in text.split("\n"):
        if not line.strip():
            continue
        try:
            envelope = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(envelope, dict):
            envelopes.append(envelope)

    if not envelopes:
        return None

    existing = await bronze_repo.list_for_recording(recording_id)
    parquet_artifacts = [a for a in existing if a.kind == "event_parquet"]
    if parquet_artifacts:
        latest = max(parquet_artifacts, key=lambda a: a.created_at)
        target_abs = parquet_root.joinpath(*parquet_rel.split("/"))
        if target_abs.exists() and latest.size_bytes > 0:
            try:
                existing_table = await asyncio.to_thread(
                    lambda: pq.read_table(target_abs, columns=["recording_id"])  # type: ignore[no-untyped-call]
                )
            except Exception as exc:
                _log.warning(
                    "compact_existing_parquet_unreadable",
                    recording_id=rec_id_str,
                    error=str(exc),
                )
            else:
                if existing_table.num_rows == len(envelopes):
                    return parquet_rel

    target_abs = parquet_root.joinpath(*parquet_rel.split("/"))
    table = _build_table(rec_id_str, envelopes)
    size_bytes = await asyncio.to_thread(_write_parquet_sync, table, target_abs)

    await bronze_repo.add(
        artifact_id=str(uuid4()),
        kind="event_parquet",
        path=parquet_rel,
        sha256="",
        size_bytes=size_bytes,
        recording_id=rec_id_str,
    )
    return parquet_rel


async def compact_all_recordings(
    bronze_store: BronzeStore,
    bronze_repo: BronzeArtifactRepository,
    *,
    parquet_root: Path,
) -> list[str]:
    """Walk every recording with a JSONL and compact it. Returns paths written.

    Used by the cron job. Errors on any one recording are logged and
    skipped — the rest still get processed.
    """
    written: list[str] = []
    files = await bronze_store.list("recordings/")
    seen: set[str] = set()
    for rel in files:
        parts = rel.split("/")
        if len(parts) < 3 or parts[0] != "recordings":
            continue
        rec_id = parts[1]
        if rec_id in seen or not _UUID_RE.match(rec_id):
            continue
        seen.add(rec_id)
        try:
            uid = UUID(rec_id)
        except ValueError:
            continue
        try:
            result = await compact_recording_jsonl_to_parquet(
                bronze_store, bronze_repo, uid, parquet_root=parquet_root,
            )
        except Exception as exc:
            _log.error(
                "compact_recording_failed",
                recording_id=rec_id,
                error=str(exc),
            )
            continue
        if result:
            written.append(result)
    return written


__all__ = [
    "compact_all_recordings",
    "compact_recording_jsonl_to_parquet",
]
