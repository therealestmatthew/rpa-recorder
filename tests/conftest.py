"""Shared pytest fixtures.

Provides:
  - `make_action` factory for the heuristic-classifier tests
  - `fake_redis` / `db_engine` / `in_process_pool` / `async_client` for the
    M12 FastAPI control plane tests
"""

from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine

from rpa_recorder.api.app import create_app
from rpa_recorder.api.streaming import WebSocketManager
from rpa_recorder.config import Config
from rpa_recorder.models import (
    ActionType,
    ClickPayload,
    ElementContext,
    ElementSelector,
    InputPayload,
    NavigatePayload,
    RecordedAction,
)
from rpa_recorder.queues import InProcessQueuePool
from rpa_recorder.storage.db import init_db

if TYPE_CHECKING:
    from httpx import AsyncClient
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncEngine

_BASE_TS = datetime(2026, 5, 4, 12, 0, 0, tzinfo=UTC)


MakeActionFactory = Callable[..., RecordedAction]


@pytest.fixture
def make_action() -> MakeActionFactory:
    """Factory: build a `RecordedAction` with sensible defaults per action_type.

    `offset_ms` is added to a fixed base timestamp so callers can express
    millisecond-level temporal relationships (used by the focus-blur and
    coalesce tests).
    """

    def _factory(
        sequence: int = 0,
        *,
        action_type: ActionType = ActionType.CLICK,
        offset_ms: int = 0,
        payload: Any = None,
        selector: ElementSelector | None = None,
        element_context: ElementContext | None = None,
        url: str = "https://example.com",
    ) -> RecordedAction:
        if payload is None:
            if action_type is ActionType.CLICK:
                payload = ClickPayload()
            elif action_type is ActionType.INPUT:
                payload = InputPayload(value="x")
            elif action_type is ActionType.NAVIGATE:
                payload = NavigatePayload(url="https://example.com")
            else:
                payload = {}
        return RecordedAction(
            sequence=sequence,
            timestamp=_BASE_TS + timedelta(milliseconds=offset_ms),
            action_type=action_type,
            payload=payload,
            selector=selector,
            element_context=element_context,
            url=url,
        )

    return _factory


# --- M12 control plane fixtures ------------------------------------------------


@pytest_asyncio.fixture
async def fake_redis() -> AsyncIterator[Redis]:
    """In-memory Redis stand-in. Cleaned up between tests."""
    import fakeredis.aioredis

    redis = fakeredis.aioredis.FakeRedis()
    try:
        yield redis
    finally:
        await redis.aclose()


@pytest_asyncio.fixture
async def db_engine(tmp_path: Any) -> AsyncIterator[AsyncEngine]:
    """Per-test SQLite engine seeded with the schema."""
    db = tmp_path / "test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db}", future=True)
    try:
        await init_db(engine)
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def in_process_pool(fake_redis: Redis) -> AsyncIterator[InProcessQueuePool]:
    """Pool with no real handlers. Tests register what they need."""
    pool = InProcessQueuePool(redis=fake_redis, registry={})
    try:
        yield pool
    finally:
        await pool.close()


@pytest_asyncio.fixture
async def ws_manager(fake_redis: Redis) -> AsyncIterator[WebSocketManager]:
    manager = WebSocketManager(
        redis=fake_redis,
        buffer_size=64,
        dedup_window=16,
        heartbeat_s=0.1,
    )
    try:
        yield manager
    finally:
        await manager.close()


@pytest.fixture
def app_under_test(
    db_engine: AsyncEngine,
    fake_redis: Redis,
    in_process_pool: InProcessQueuePool,
    ws_manager: WebSocketManager,
) -> Any:
    """A FastAPI app with state patched for unit tests (lifespan does NOT run)."""
    app = create_app(Config())
    app.state.engine = db_engine
    app.state.redis = fake_redis
    app.state.queue_pool = in_process_pool
    app.state.ws_manager = ws_manager
    return app


@pytest_asyncio.fixture
async def async_client(app_under_test: Any) -> AsyncIterator[AsyncClient]:
    """ASGI-bound httpx client wired to `app_under_test`."""
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=app_under_test)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
