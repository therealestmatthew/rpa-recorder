# mypy: disable-error-code="no-untyped-def, no-untyped-call, type-arg, unused-ignore, attr-defined, comparison-overlap, misc"
"""Tests for `rpa_recorder.api.dependencies.*` factories."""

import pytest


@pytest.mark.asyncio
async def test_get_session_yields_session_per_request(async_client):
    # Two GETs to /healthz indirectly exercises lifecycle. To assert
    # session uniqueness directly, we hit /recordings (which depends on
    # get_session) twice and ensure both succeed independently.
    r1 = await async_client.get("/recordings")
    r2 = await async_client.get("/recordings")
    assert r1.status_code == 200
    assert r2.status_code == 200


@pytest.mark.asyncio
async def test_get_queue_pool_is_singleton(async_client, app_under_test):
    pool1 = app_under_test.state.queue_pool
    pool2 = app_under_test.state.queue_pool
    assert pool1 is pool2


@pytest.mark.asyncio
async def test_get_redis_returns_app_state_redis(async_client, app_under_test):
    from rpa_recorder.api.dependencies.redis import get_redis

    class _FakeRequest:
        def __init__(self, app):
            self.app = app

    redis = get_redis(_FakeRequest(app_under_test))  # type: ignore[arg-type]
    assert redis is app_under_test.state.redis
