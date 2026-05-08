"""FastAPI dependency-injection factories backed by `app.state`."""

from rpa_recorder.api.dependencies.config import get_config
from rpa_recorder.api.dependencies.db import get_session
from rpa_recorder.api.dependencies.queue import get_queue_pool
from rpa_recorder.api.dependencies.redis import get_redis
from rpa_recorder.api.dependencies.ws_manager import get_ws_manager

__all__ = [
    "get_config",
    "get_queue_pool",
    "get_redis",
    "get_session",
    "get_ws_manager",
]
