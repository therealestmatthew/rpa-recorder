"""Progress publishing helpers shared by every queue backend.

`publish_progress` writes each event to BOTH `PUBLISH run:{id}` (for live
subscribers) and `LPUSH events:{id}` capped at `ws_event_buffer_size` (for
WebSocket subscribers that connect after a run started). M11.5's worker
imports this same helper.
"""

import json
from contextlib import suppress
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import structlog

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from redis.asyncio import Redis


_log = structlog.get_logger(__name__)


_CHANNEL_PREFIX = "run"
_LIST_PREFIX = "events"
_DEFAULT_BUFFER_SIZE = 1000


def _channel(run_id: str | UUID) -> str:
    return f"{_CHANNEL_PREFIX}:{run_id}"


def _list_key(run_id: str | UUID) -> str:
    return f"{_LIST_PREFIX}:{run_id}"


async def publish_progress(
    redis: Redis,
    run_id: str | UUID,
    event: dict[str, Any],
    *,
    buffer_size: int = _DEFAULT_BUFFER_SIZE,
) -> None:
    """Stamp `event` with `event_id` + `ts` and publish + buffer it under `run_id`.

    `event` is mutated to add `event_id` (uuid4) and `ts` (UTC iso) when missing.
    Buffer is trimmed to `buffer_size` newest entries via `LPUSH` + `LTRIM 0 N-1`.
    Failures are logged but never raised — a broken Redis must not fail a job.
    """
    event.setdefault("event_id", str(uuid4()))
    event.setdefault("ts", datetime.now(UTC).isoformat())
    payload = json.dumps(event, default=str)
    try:
        async with redis.pipeline(transaction=False) as pipe:
            pipe.publish(_channel(run_id), payload)
            pipe.lpush(_list_key(run_id), payload)
            pipe.ltrim(_list_key(run_id), 0, buffer_size - 1)
            await pipe.execute()
    except Exception as exc:
        _log.warning(
            "publish_progress_failed",
            run_id=str(run_id),
            event_type=event.get("type"),
            error=str(exc),
        )


async def backfill_events(redis: Redis, run_id: str | UUID) -> list[dict[str, Any]]:
    """Return buffered events for `run_id` in chronological order (oldest first)."""
    raw: list[Any] = await redis.lrange(_list_key(run_id), 0, -1)  # type: ignore[misc]
    out: list[dict[str, Any]] = []
    for item in reversed(raw):  # LPUSH stores newest-first; reverse for chronological
        try:
            text = item.decode("utf-8") if isinstance(item, bytes) else item
            out.append(json.loads(text))
        except UnicodeDecodeError, json.JSONDecodeError:
            continue
    return out


async def subscribe_run(redis: Redis, run_id: str | UUID) -> AsyncIterator[dict[str, Any]]:
    """Yield decoded events from `run:{id}` until the pub/sub closes.

    Caller is responsible for cancelling the iterator (e.g. via `task.cancel()`)
    on disconnect; the helper unsubscribes cleanly on shutdown.
    """
    pubsub = redis.pubsub()
    await pubsub.subscribe(_channel(run_id))
    try:
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            data = message.get("data")
            if isinstance(data, bytes):
                data = data.decode("utf-8")
            if not isinstance(data, str):
                continue
            try:
                yield json.loads(data)
            except json.JSONDecodeError:
                continue
    finally:
        with suppress(Exception):
            await pubsub.unsubscribe(_channel(run_id))
        with suppress(Exception):
            await pubsub.aclose()  # type: ignore[no-untyped-call]


__all__ = ["backfill_events", "publish_progress", "subscribe_run"]
