# mypy: disable-error-code="no-untyped-def, no-untyped-call, type-arg, unused-ignore, attr-defined, comparison-overlap, misc"
"""Tests for `/medallion/*` endpoints."""

import pytest


@pytest.mark.asyncio
async def test_recompute_returns_deferred_under_in_process_backend(async_client):
    r = await async_client.post("/medallion/recompute", json={})
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "deferred"
    assert "M11.5" in (body.get("reason") or "")


@pytest.mark.asyncio
async def test_compact_returns_deferred_under_in_process_backend(async_client):
    r = await async_client.post("/medallion/compact")
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "deferred"


@pytest.mark.asyncio
async def test_status_returns_layer_freshness(async_client):
    r = await async_client.get("/medallion/status")
    assert r.status_code == 200
    body = r.json()
    assert body["queue_backend"] == "in_process"
    assert body["bronze_artifact_count"] == 0
    assert body["bronze_recordings"] == 0
    assert body["last_replay_at"] is None
    assert any("M11.5" in n for n in body["notes"])
