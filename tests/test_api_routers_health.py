# mypy: disable-error-code="no-untyped-def, no-untyped-call, type-arg, unused-ignore, attr-defined, comparison-overlap, misc"
"""Tests for `/healthz` and `/readyz`."""

import pytest


@pytest.mark.asyncio
async def test_healthz_returns_ok(async_client):
    r = await async_client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


@pytest.mark.asyncio
async def test_readyz_pings_dependencies(async_client):
    r = await async_client.get("/readyz")
    assert r.status_code == 200
    body = r.json()
    assert body["db"] == "ok"
    assert body["redis"] == "ok"
    assert body["queue"] == "ok"


@pytest.mark.asyncio
async def test_readyz_503_when_redis_fails(async_client, app_under_test, monkeypatch):
    async def boom() -> None:
        raise RuntimeError("redis down")

    monkeypatch.setattr(app_under_test.state.redis, "ping", boom)
    r = await async_client.get("/readyz")
    assert r.status_code == 503
    assert r.json()["redis"] == "fail"
