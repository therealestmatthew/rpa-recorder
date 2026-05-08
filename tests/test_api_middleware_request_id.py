# mypy: disable-error-code="no-untyped-def, no-untyped-call, type-arg, unused-ignore, attr-defined, comparison-overlap, misc"
"""Tests for `RequestIdMiddleware`."""

import pytest


@pytest.mark.asyncio
async def test_request_id_added_to_response_when_missing(async_client):
    r = await async_client.get("/healthz")
    assert "x-request-id" in {k.lower() for k in r.headers}
    assert r.headers["x-request-id"]


@pytest.mark.asyncio
async def test_request_id_preserved_when_provided(async_client):
    r = await async_client.get("/healthz", headers={"X-Request-ID": "abc-123"})
    assert r.headers["x-request-id"] == "abc-123"
