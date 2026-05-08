"""Cold gold: DuckDB on Parquet (M11.5).

Three cross-recording tables (`classifier_accuracy`, `llm_costs_daily`,
`training_data`) plus a per-recording `replay_scripts/<recording_id>.parquet`.
Each is recomputed by reading silver via SQLAlchemy, building a pyarrow
Table, and writing it atomically (temp + rename). DuckDB-on-Parquet is
the read path for ad-hoc queries.

Sync libs (DuckDB, pyarrow) are wrapped in `asyncio.to_thread` so the
event loop stays unblocked during recompute.
"""

import asyncio
import tempfile
from collections import defaultdict
from datetime import UTC
from pathlib import Path
from typing import TYPE_CHECKING, Any

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import structlog
from sqlalchemy import select

from rpa_recorder.storage.db import (
    LLMCallRow,
    RecordedActionRow,
)

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

_log = structlog.get_logger(__name__)


def _atomic_write_parquet(table: pa.Table, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix="rpa_cold_",
        suffix=".parquet",
        dir=target.parent,
        delete=False,
    ) as tmp:
        tmp_path = Path(tmp.name)
    try:
        pq.write_table(table, tmp_path, compression="snappy")  # type: ignore[no-untyped-call]
        tmp_path.replace(target)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


class ColdGold:
    """DuckDB-backed analytics tables stored as Parquet under `root`."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root)

    @property
    def root(self) -> Path:
        return self._root

    def _table_path(self, name: str) -> Path:
        return self._root / f"{name}.parquet"

    def _replay_script_path(self, recording_id: UUID | str) -> Path:
        return self._root / "replay_scripts" / f"{recording_id}.parquet"

    async def recompute_classifier_accuracy(self, session: AsyncSession) -> None:
        """Per-action: confirmed semantic intent vs the classifier's guess."""
        rows = list(
            (
                await session.execute(
                    select(RecordedActionRow).where(RecordedActionRow.user_confirmed.is_(True))
                )
            ).scalars()
        )
        cols: dict[str, list[Any]] = {
            "recording_id": [],
            "action_id": [],
            "predicted_intent": [],
            "confirmed_intent": [],
            "confidence": [],
            "correct": [],
        }
        for row in rows:
            confirmed = row.user_label or row.semantic_intent
            cols["recording_id"].append(row.recording_id)
            cols["action_id"].append(row.id)
            cols["predicted_intent"].append(row.semantic_intent)
            cols["confirmed_intent"].append(confirmed)
            cols["confidence"].append(row.classification_confidence)
            cols["correct"].append(row.semantic_intent == confirmed)
        table = pa.Table.from_pydict(cols)
        target = self._table_path("classifier_accuracy")
        await asyncio.to_thread(_atomic_write_parquet, table, target)

    async def recompute_llm_costs_daily(self, session: AsyncSession) -> None:
        """Day-bucketed input/output token totals across all LLM calls."""
        rows = list((await session.execute(select(LLMCallRow))).scalars())
        buckets: dict[Any, dict[str, int]] = defaultdict(
            lambda: {"input_tokens": 0, "output_tokens": 0, "calls": 0}
        )
        for row in rows:
            created = row.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=UTC)
            day = created.astimezone(UTC).date()
            buckets[day]["input_tokens"] += int(row.input_tokens or 0)
            buckets[day]["output_tokens"] += int(row.output_tokens or 0)
            buckets[day]["calls"] += 1
        cols: dict[str, list[Any]] = {
            "day": [],
            "calls": [],
            "input_tokens": [],
            "output_tokens": [],
        }
        for day, agg in sorted(buckets.items()):
            cols["day"].append(day)
            cols["calls"].append(agg["calls"])
            cols["input_tokens"].append(agg["input_tokens"])
            cols["output_tokens"].append(agg["output_tokens"])
        table = pa.Table.from_pydict(cols)
        target = self._table_path("llm_costs_daily")
        await asyncio.to_thread(_atomic_write_parquet, table, target)

    async def recompute_training_data(self, session: AsyncSession) -> None:
        """Confirmed (action_text, intent) pairs for ML fine-tuning."""
        rows = list(
            (
                await session.execute(
                    select(RecordedActionRow).where(RecordedActionRow.user_confirmed.is_(True))
                )
            ).scalars()
        )
        cols: dict[str, list[Any]] = {
            "recording_id": [],
            "action_id": [],
            "action_type": [],
            "intent": [],
            "selector_text": [],
            "url": [],
        }
        for row in rows:
            selector_dict = row.selector or {}
            selector_text = (
                selector_dict.get("accessible_name")
                or selector_dict.get("text_content")
                or selector_dict.get("css")
                or ""
            )
            cols["recording_id"].append(row.recording_id)
            cols["action_id"].append(row.id)
            cols["action_type"].append(row.action_type)
            cols["intent"].append(row.user_label or row.semantic_intent)
            cols["selector_text"].append(str(selector_text))
            cols["url"].append(row.url)
        table = pa.Table.from_pydict(cols)
        target = self._table_path("training_data")
        await asyncio.to_thread(_atomic_write_parquet, table, target)

    async def recompute_replay_scripts(self, session: AsyncSession, recording_id: UUID) -> None:
        """Per-recording sequenced action script with confirmed labels."""
        rows = list(
            (
                await session.execute(
                    select(RecordedActionRow)
                    .where(RecordedActionRow.recording_id == str(recording_id))
                    .order_by(RecordedActionRow.sequence)
                )
            ).scalars()
        )
        cols: dict[str, list[Any]] = {
            "sequence": [],
            "action_id": [],
            "action_type": [],
            "intent": [],
            "url": [],
            "user_confirmed": [],
        }
        for row in rows:
            cols["sequence"].append(row.sequence)
            cols["action_id"].append(row.id)
            cols["action_type"].append(row.action_type)
            cols["intent"].append(row.user_label or row.semantic_intent)
            cols["url"].append(row.url)
            cols["user_confirmed"].append(bool(row.user_confirmed))
        table = pa.Table.from_pydict(cols)
        target = self._replay_script_path(recording_id)
        await asyncio.to_thread(_atomic_write_parquet, table, target)

    def query(self, sql: str) -> pa.Table:
        """Run a one-shot DuckDB SQL query rooted at `self._root`.

        Tables can be referenced as `'<root>/<name>.parquet'` literals.
        Sync — caller wraps in `asyncio.to_thread` if invoked from async.
        """
        con = duckdb.connect(database=":memory:", read_only=False)
        try:
            return con.sql(sql).to_arrow_table()
        finally:
            con.close()


__all__ = ["ColdGold"]
