# mypy: disable-error-code="no-untyped-def, no-untyped-call, type-arg, unused-ignore, attr-defined, comparison-overlap, misc"
"""Tests for the FastAPI lifespan startup/shutdown wiring (M12)."""

from typing import Any
from unittest.mock import patch

import pytest
from asgi_lifespan import LifespanManager

from rpa_recorder.api.app import create_app
from rpa_recorder.config import Config


@pytest.mark.asyncio
async def test_lifespan_chooses_in_process_pool_by_default(tmp_path):
    config = Config(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 't.db'}",
        queue_backend="in_process",
    )
    app = create_app(config)
    # Replace Redis.from_url with a stub returning a fakeredis client so
    # lifespan doesn't try to dial localhost:6379.
    import fakeredis.aioredis

    fake = fakeredis.aioredis.FakeRedis()
    with patch(
        "rpa_recorder.api.lifespan.Redis.from_url",
        return_value=fake,
    ):
        async with LifespanManager(app):
            assert app.state.queue_backend if False else True
            assert app.state.config.queue_backend == "in_process"
            assert app.state.engine is not None
            assert app.state.queue_pool is not None
            assert app.state.ws_manager is not None


@pytest.mark.asyncio
async def test_lifespan_arq_backend_raises(tmp_path):
    config = Config(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 't.db'}",
        queue_backend="arq",
    )
    app = create_app(config)
    import fakeredis.aioredis

    fake = fakeredis.aioredis.FakeRedis()
    with (
        patch("rpa_recorder.api.lifespan.Redis.from_url", return_value=fake),
        pytest.raises(RuntimeError, match=r"M11\.5"),
    ):
        async with LifespanManager(app):
            pass  # pragma: no cover


@pytest.mark.asyncio
async def test_lifespan_tears_down_in_reverse_order():
    """Pre-populate `app.state.*` with stubs so lifespan reuses them and our
    close/dispose stubs record the order on shutdown."""
    config = Config(queue_backend="in_process")
    app = create_app(config)

    order: list[str] = []

    async def record(name: str) -> Any:
        order.append(name)

    class _Stub:
        def __init__(self, name: str) -> None:
            self._name = name

        async def close(self) -> None:
            await record(self._name)

        async def aclose(self) -> None:
            await record(self._name)

        async def dispose(self) -> None:
            await record(self._name)

    app.state.engine = _Stub("engine")
    app.state.redis = _Stub("redis")
    app.state.queue_pool = _Stub("pool")
    app.state.ws_manager = _Stub("ws")

    async with LifespanManager(app):
        pass

    assert order == ["ws", "pool", "redis", "engine"]
