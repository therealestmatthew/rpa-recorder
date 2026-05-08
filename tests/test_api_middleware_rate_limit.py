# mypy: disable-error-code="no-untyped-def, no-untyped-call, type-arg, unused-ignore, attr-defined, comparison-overlap, misc"
"""Tests for `RateLimitMiddleware`."""

import pytest

from rpa_recorder.api.app import create_app
from rpa_recorder.config import Config


@pytest.mark.asyncio
async def test_rate_limit_allows_under_threshold(async_client):
    for _ in range(5):
        r = await async_client.get("/healthz")
        assert r.status_code == 200


@pytest.mark.asyncio
async def test_rate_limit_returns_429_when_exceeded(
    fake_redis, db_engine, in_process_pool, ws_manager
):
    from httpx import ASGITransport, AsyncClient

    app = create_app(Config(rate_limit_per_minute=2))
    app.state.engine = db_engine
    app.state.redis = fake_redis
    app.state.queue_pool = in_process_pool
    app.state.ws_manager = ws_manager

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r1 = await client.get("/healthz")
        r2 = await client.get("/healthz")
        r3 = await client.get("/healthz")
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r3.status_code == 429
    assert "retry-after" in {k.lower() for k in r3.headers}
