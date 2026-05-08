"""`WebSocketManager` — bridges Redis pub/sub `run:{id}` channels to WebSockets.

Behavior:

- One pub/sub subscription per active run, refcounted by subscriber count.
- Per-subscriber bounded `asyncio.Queue` between the pub/sub reader and
  `ws.send_json`. On overflow, the oldest event is dropped with a structlog
  warning (the connection is preserved).
- Backfill: on subscribe, drain `events:{id}` (LRANGE) and forward each
  buffered event before pub/sub deliveries. A small dedup window suppresses
  duplicates that fall in the LRANGE→SUBSCRIBE race window.
- Heartbeat: sends `{"type": "heartbeat", "ts": ...}` every
  `heartbeat_s` seconds so clients can detect stale connections.
- Disconnect: a tiny "drain receive" task per subscriber catches
  `WebSocketDisconnect` and signals shutdown so the sender doesn't hang on a
  dead socket.
"""

import asyncio
import json
from collections import deque
from contextlib import suppress
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog
from starlette.websockets import WebSocketDisconnect, WebSocketState

from rpa_recorder.queues.events import backfill_events

if TYPE_CHECKING:
    from uuid import UUID

    from fastapi import WebSocket
    from redis.asyncio import Redis
    from redis.asyncio.client import PubSub


_log = structlog.get_logger(__name__)


class _RunChannel:
    """Per-run pub/sub state shared by every subscriber on that run."""

    __slots__ = ("pubsub", "reader_task", "ref_count", "subscribers")

    def __init__(self) -> None:
        self.pubsub: PubSub | None = None
        self.ref_count = 0
        self.reader_task: asyncio.Task[None] | None = None
        self.subscribers: list[_Subscriber] = []


class _Subscriber:
    __slots__ = ("dedup", "queue", "shutdown")

    def __init__(self, queue_size: int, dedup_window: int) -> None:
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=queue_size)
        self.shutdown: asyncio.Event = asyncio.Event()
        self.dedup: deque[str] = deque(maxlen=dedup_window)

    def has_seen(self, event_id: str | None) -> bool:
        if not event_id:
            return False
        if event_id in self.dedup:
            return True
        self.dedup.append(event_id)
        return False


class WebSocketManager:
    """Pub/sub fan-out with backfill, heartbeat, and bounded per-subscriber buffers."""

    def __init__(
        self,
        *,
        redis: Redis,
        buffer_size: int = 1000,
        dedup_window: int = 64,
        heartbeat_s: float = 30.0,
    ) -> None:
        self._redis = redis
        self._buffer_size = buffer_size
        self._dedup_window = dedup_window
        self._heartbeat_s = heartbeat_s
        self._channels: dict[str, _RunChannel] = {}
        self._lock = asyncio.Lock()
        self._closed = False

    async def subscribe(self, run_id: str | UUID, ws: WebSocket) -> None:
        """Run for the lifetime of one WebSocket connection.

        Sequence: backfill → subscribe to pub/sub → spawn heartbeat + receive
        drain → forward events until disconnect → decrement refcount.
        """
        if self._closed:
            await ws.close(code=1013, reason="server shutting down")
            return
        rid = str(run_id)
        sub = _Subscriber(self._buffer_size, self._dedup_window)
        channel = await self._acquire_channel(rid, sub)
        send_task = asyncio.create_task(self._sender(ws, sub), name=f"ws-send:{rid}")
        heartbeat_task = asyncio.create_task(self._heartbeat(ws, sub), name=f"ws-heartbeat:{rid}")
        receive_task = asyncio.create_task(self._receiver(ws, sub), name=f"ws-recv:{rid}")
        try:
            await self._backfill(rid, sub)
            await sub.shutdown.wait()
        finally:
            for task in (send_task, heartbeat_task, receive_task):
                task.cancel()
            await asyncio.gather(send_task, heartbeat_task, receive_task, return_exceptions=True)
            await self._release_channel(rid, sub, channel)
            if ws.client_state != WebSocketState.DISCONNECTED:
                with suppress(Exception):
                    await ws.close()

    async def close(self) -> None:
        """Drain every active subscriber on app shutdown."""
        if self._closed:
            return
        self._closed = True
        async with self._lock:
            channels = list(self._channels.values())
            self._channels.clear()
        for channel in channels:
            for sub in channel.subscribers:
                sub.shutdown.set()
            if channel.reader_task is not None:
                channel.reader_task.cancel()
            if channel.pubsub is not None:
                with suppress(Exception):
                    await channel.pubsub.aclose()  # type: ignore[no-untyped-call]

    # ----- internals --------------------------------------------------------

    async def _acquire_channel(self, run_id: str, sub: _Subscriber) -> _RunChannel:
        async with self._lock:
            channel = self._channels.get(run_id)
            if channel is None:
                channel = _RunChannel()
                pubsub = self._redis.pubsub()
                await pubsub.subscribe(f"run:{run_id}")
                channel.pubsub = pubsub
                channel.reader_task = asyncio.create_task(
                    self._reader(run_id, channel), name=f"ws-reader:{run_id}"
                )
                self._channels[run_id] = channel
            channel.ref_count += 1
            channel.subscribers.append(sub)
            return channel

    async def _release_channel(self, run_id: str, sub: _Subscriber, channel: _RunChannel) -> None:
        async with self._lock:
            with suppress(ValueError):
                channel.subscribers.remove(sub)
            channel.ref_count -= 1
            if channel.ref_count > 0:
                return
            self._channels.pop(run_id, None)
        if channel.reader_task is not None:
            channel.reader_task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await channel.reader_task
        if channel.pubsub is not None:
            with suppress(Exception):
                await channel.pubsub.unsubscribe(f"run:{run_id}")
            with suppress(Exception):
                await channel.pubsub.aclose()  # type: ignore[no-untyped-call]

    async def _reader(self, run_id: str, channel: _RunChannel) -> None:
        """Pull messages from this run's pub/sub and fan-out to every subscriber."""
        pubsub = channel.pubsub
        if pubsub is None:
            return
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
                    event = json.loads(data)
                except json.JSONDecodeError:
                    continue
                await self._fanout(channel, event)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _log.warning(
                "ws_reader_failed",
                run_id=run_id,
                error=str(exc),
                error_type=type(exc).__name__,
            )

    async def _fanout(self, channel: _RunChannel, event: dict[str, Any]) -> None:
        for sub in list(channel.subscribers):
            if sub.has_seen(event.get("event_id")):
                continue
            try:
                sub.queue.put_nowait(event)
            except asyncio.QueueFull:
                with suppress(asyncio.QueueEmpty):
                    sub.queue.get_nowait()
                _log.warning("ws_subscriber_buffer_overflow", event_type=event.get("type"))
                with suppress(asyncio.QueueFull):
                    sub.queue.put_nowait(event)

    async def _backfill(self, run_id: str, sub: _Subscriber) -> None:
        try:
            buffered = await backfill_events(self._redis, run_id)
        except Exception as exc:
            _log.warning("ws_backfill_failed", run_id=run_id, error=str(exc))
            return
        for event in buffered:
            if sub.has_seen(event.get("event_id")):
                continue
            try:
                sub.queue.put_nowait(event)
            except asyncio.QueueFull:
                with suppress(asyncio.QueueEmpty):
                    sub.queue.get_nowait()
                with suppress(asyncio.QueueFull):
                    sub.queue.put_nowait(event)

    async def _sender(self, ws: WebSocket, sub: _Subscriber) -> None:
        try:
            while not sub.shutdown.is_set():
                try:
                    event = await asyncio.wait_for(sub.queue.get(), timeout=1.0)
                except TimeoutError:
                    continue
                try:
                    await ws.send_json(event)
                except WebSocketDisconnect, RuntimeError:
                    sub.shutdown.set()
                    return
        except asyncio.CancelledError:
            raise

    async def _heartbeat(self, ws: WebSocket, sub: _Subscriber) -> None:
        try:
            while not sub.shutdown.is_set():
                try:
                    await asyncio.wait_for(sub.shutdown.wait(), timeout=self._heartbeat_s)
                    return
                except TimeoutError:
                    pass
                heartbeat = {"type": "heartbeat", "ts": datetime.now(UTC).isoformat()}
                try:
                    await ws.send_json(heartbeat)
                except WebSocketDisconnect, RuntimeError:
                    sub.shutdown.set()
                    return
        except asyncio.CancelledError:
            raise

    async def _receiver(self, ws: WebSocket, sub: _Subscriber) -> None:
        """Drain inbound frames so we notice disconnects promptly."""
        try:
            while not sub.shutdown.is_set():
                try:
                    await ws.receive_text()
                except WebSocketDisconnect:
                    sub.shutdown.set()
                    return
                except RuntimeError:
                    sub.shutdown.set()
                    return
        except asyncio.CancelledError:
            raise


__all__ = ["WebSocketManager"]
