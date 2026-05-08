"""WebSocket fan-out — multiplexes Redis pub/sub channels to subscribers."""

from rpa_recorder.api.streaming.manager import WebSocketManager

__all__ = ["WebSocketManager"]
