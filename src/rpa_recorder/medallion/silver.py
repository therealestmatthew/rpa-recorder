"""Bronze → Silver promotion (M11.5).

Re-derives `RecordedActionRow` rows from the bronze raw-events JSONL. The
common path is a no-op: the recorder writes silver rows directly during
capture, so silver count equals JSONL line count and this function returns
zero. The slow path covers recovery — bronze survived but the DB was
recreated — by parsing each envelope and inserting fresh rows.

Idempotent: silver count is checked before any inserts, and the read of
bronze is purely streaming. Malformed envelopes are logged and skipped so
one bad line doesn't poison the whole batch.
"""

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog
from pydantic import ValidationError
from sqlalchemy import func, select

from rpa_recorder.medallion import paths
from rpa_recorder.models import (
    ActionType,
    ClickPayload,
    ElementContext,
    ElementSelector,
    InputPayload,
    SelectPayload,
)
from rpa_recorder.storage.db import RecordedActionRow

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from rpa_recorder.medallion.bronze_store import BronzeStore
    from rpa_recorder.models.actions import ActionPayload

_log = structlog.get_logger(__name__)


_PAYLOAD_BY_EVENT: dict[str, type] = {
    "click": ClickPayload,
    "input": InputPayload,
}


def _build_payload(
    event_type: str, target: dict[str, Any], payload_dict: dict[str, Any]
) -> tuple[ActionType, ActionPayload] | None:
    if event_type == "click":
        return ActionType.CLICK, ClickPayload(**payload_dict)
    if event_type == "input":
        return ActionType.INPUT, InputPayload(**payload_dict)
    if event_type == "change":
        tag = str(target.get("tag") or "").lower()
        if tag == "select":
            return ActionType.SELECT, SelectPayload(**payload_dict)
        return ActionType.INPUT, InputPayload(**payload_dict)
    if event_type == "keydown":
        return ActionType.KEY_PRESS, dict(payload_dict)
    return None


def _envelope_to_row(
    raw: dict[str, Any],
    *,
    recording_id: str,
    sequence: int,
) -> RecordedActionRow | None:
    """Mirror of `Recorder._build_action`, returning a row instead of a model.

    Why mirror instead of import: the recorder's method is bound to a
    `Page` instance for `page.url`. Silver promotion has no page; it
    pulls `url` from the envelope itself.
    """
    event_type = raw.get("event_type")
    if not isinstance(event_type, str):
        return None

    target = raw.get("target") or {}
    payload_dict = raw.get("payload") or {}
    if not isinstance(target, dict) or not isinstance(payload_dict, dict):
        return None

    built = _build_payload(event_type, target, payload_dict)
    if built is None:
        return None
    action_type, payload = built

    selector = ElementSelector(
        role=target.get("role"),
        accessible_name=target.get("accessible_name"),
        test_id=target.get("test_id"),
        text_content=target.get("visible_text"),
        css=target.get("css"),
        xpath=target.get("xpath"),
        frame_url=raw.get("frame_url"),
    )
    element_context = ElementContext(
        tag=str(target.get("tag") or ""),
        attributes=dict(target.get("attributes") or {}),
        visible_text=target.get("visible_text"),
        bounding_box=target.get("bounding_box"),
        is_visible=bool(target.get("is_visible", True)),
        is_enabled=bool(target.get("is_enabled", True)),
        parent_form_id=target.get("parent_form_id"),
        nearby_labels=list(target.get("nearby_labels") or []),
    )

    ts_ms = raw.get("timestamp_ms")
    if isinstance(ts_ms, int | float) and not isinstance(ts_ms, bool):
        timestamp = datetime.fromtimestamp(float(ts_ms) / 1000.0, tz=UTC)
    else:
        timestamp = datetime.now(UTC)

    payload_serializable = payload.model_dump() if hasattr(payload, "model_dump") else dict(payload)

    return RecordedActionRow(
        recording_id=recording_id,
        sequence=sequence,
        timestamp=timestamp,
        action_type=action_type.value,
        url=str(raw.get("url") or ""),
        page_title=raw.get("page_title"),
        frame_url=raw.get("frame_url"),
        payload=payload_serializable,
        selector=selector.model_dump(),
        element_context=element_context.model_dump(),
        viewport=raw.get("viewport") if isinstance(raw.get("viewport"), dict) else None,
    )


async def promote_bronze_to_silver(
    session: AsyncSession,
    bronze_store: BronzeStore,
    recording_id: UUID,
) -> int:
    """Re-derive silver rows from bronze JSONL. Returns the number inserted.

    Idempotent: if the silver count already matches the JSONL line count,
    returns zero without touching the store. Caller owns the transaction
    (per the M5 caller-owns-session pattern).
    """
    rec_id_str = str(recording_id)

    existing_count = (
        await session.execute(
            select(func.count(RecordedActionRow.id)).where(
                RecordedActionRow.recording_id == rec_id_str
            )
        )
    ).scalar_one()

    try:
        raw_bytes = await bronze_store.get(paths.recording_events_jsonl(recording_id))
    except FileNotFoundError:
        return 0

    text = raw_bytes.decode("utf-8")
    lines = [line for line in text.split("\n") if line.strip()]
    if existing_count >= len(lines):
        return 0

    inserted = 0
    sequence = existing_count
    for index, line in enumerate(lines[existing_count:], start=existing_count):
        try:
            envelope = json.loads(line)
        except json.JSONDecodeError as exc:
            _log.warning(
                "silver_skip_malformed_json",
                recording_id=rec_id_str,
                line_index=index,
                error=str(exc),
            )
            continue
        if not isinstance(envelope, dict):
            _log.warning(
                "silver_skip_non_dict_envelope",
                recording_id=rec_id_str,
                line_index=index,
            )
            continue
        try:
            sequence += 1
            row = _envelope_to_row(envelope, recording_id=rec_id_str, sequence=sequence)
        except (ValidationError, ValueError, TypeError) as exc:
            _log.warning(
                "silver_skip_invalid_envelope",
                recording_id=rec_id_str,
                line_index=index,
                error=str(exc),
            )
            sequence -= 1
            continue
        if row is None:
            sequence -= 1
            continue
        session.add(row)
        inserted += 1

    if inserted:
        await session.flush()
    return inserted


__all__ = ["promote_bronze_to_silver"]
