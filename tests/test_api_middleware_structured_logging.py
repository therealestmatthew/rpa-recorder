# mypy: disable-error-code="no-untyped-def, no-untyped-call, type-arg, unused-ignore, attr-defined, comparison-overlap, misc"
"""Tests for `StructuredLoggingMiddleware`."""

import pytest
import structlog


@pytest.mark.asyncio
async def test_structlog_context_unbound_after_request(async_client):
    # Request itself should bind/unbind cleanly. Outside the request, context
    # should be empty.
    r = await async_client.get("/healthz")
    assert r.status_code == 200
    ctx = structlog.contextvars.get_contextvars()
    assert "request_id" not in ctx
    assert "method" not in ctx
    assert "path" not in ctx
