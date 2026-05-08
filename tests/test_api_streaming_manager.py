# mypy: disable-error-code="no-untyped-def, no-untyped-call, type-arg, unused-ignore, attr-defined, comparison-overlap, misc, assignment"
"""Unit tests for `WebSocketManager` against fakeredis (no real WebSocket)."""

import asyncio

import pytest

from rpa_recorder.api.streaming import WebSocketManager
from rpa_recorder.queues.events import publish_progress


class _StubWebSocket:
    """Minimal stand-in for `fastapi.WebSocket` exposing `send_json` + `receive_text`."""

    def __init__(self) -> None:
        self.sent: list[dict] = []
        self._receive = asyncio.Event()
        self.client_state = _ConnectedState()

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)

    async def receive_text(self) -> str:
        await self._receive.wait()
        from starlette.websockets import WebSocketDisconnect

        raise WebSocketDisconnect()

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.client_state = _DisconnectedState()

    def disconnect(self) -> None:
        self._receive.set()


class _ConnectedState:
    name = "CONNECTED"


class _DisconnectedState:
    name = "DISCONNECTED"


@pytest.mark.asyncio
async def test_manager_forwards_pubsub_messages_to_subscriber(fake_redis):
    manager = WebSocketManager(redis=fake_redis, buffer_size=64, dedup_window=8, heartbeat_s=10.0)
    ws = _StubWebSocket()

    sub_task = asyncio.create_task(manager.subscribe("run-1", ws))  # type: ignore[arg-type]
    await asyncio.sleep(0.05)  # Let manager subscribe to pub/sub.

    await publish_progress(fake_redis, "run-1", {"type": "x", "n": 1})
    await publish_progress(fake_redis, "run-1", {"type": "x", "n": 2})

    # Wait until both events are sent.
    for _ in range(50):
        if len(ws.sent) >= 2:
            break
        await asyncio.sleep(0.02)

    ns = [s["n"] for s in ws.sent if s.get("type") == "x"]
    assert ns == [1, 2]

    ws.disconnect()
    await asyncio.wait_for(sub_task, timeout=1.0)
    await manager.close()


@pytest.mark.asyncio
async def test_manager_backfills_buffered_events_before_subscribing(fake_redis):
    # Pre-publish events so they're in the LIST before any subscriber exists.
    for i in range(3):
        await publish_progress(fake_redis, "run-2", {"type": "back", "i": i})

    manager = WebSocketManager(redis=fake_redis, buffer_size=64, dedup_window=8, heartbeat_s=10.0)
    ws = _StubWebSocket()
    sub_task = asyncio.create_task(manager.subscribe("run-2", ws))  # type: ignore[arg-type]

    for _ in range(50):
        if len(ws.sent) >= 3:
            break
        await asyncio.sleep(0.02)

    indices = [s["i"] for s in ws.sent if s.get("type") == "back"]
    assert indices == [0, 1, 2]

    ws.disconnect()
    await asyncio.wait_for(sub_task, timeout=1.0)
    await manager.close()


@pytest.mark.asyncio
async def test_manager_sends_heartbeat(fake_redis):
    manager = WebSocketManager(redis=fake_redis, buffer_size=8, dedup_window=4, heartbeat_s=0.05)
    ws = _StubWebSocket()
    sub_task = asyncio.create_task(manager.subscribe("run-3", ws))  # type: ignore[arg-type]

    for _ in range(50):
        if any(s.get("type") == "heartbeat" for s in ws.sent):
            break
        await asyncio.sleep(0.02)

    assert any(s.get("type") == "heartbeat" for s in ws.sent)

    ws.disconnect()
    await asyncio.wait_for(sub_task, timeout=1.0)
    await manager.close()


@pytest.mark.asyncio
async def test_manager_close_drains_active_subscriber(fake_redis):
    manager = WebSocketManager(redis=fake_redis, buffer_size=4, dedup_window=4, heartbeat_s=10.0)
    ws = _StubWebSocket()
    sub_task = asyncio.create_task(manager.subscribe("run-4", ws))  # type: ignore[arg-type]
    await asyncio.sleep(0.05)
    await manager.close()
    # subscribe() should now exit because shutdown was set.
    await asyncio.wait_for(sub_task, timeout=1.0)
