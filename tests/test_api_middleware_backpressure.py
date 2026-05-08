# mypy: disable-error-code="no-untyped-def, no-untyped-call, type-arg, unused-ignore, attr-defined, comparison-overlap, misc"
"""Tests for `BackpressureMiddleware`."""

import pytest


@pytest.mark.asyncio
async def test_backpressure_only_protects_replay_path(async_client, app_under_test):
    async def fake_size(_name: str) -> int:
        return 10_000

    app_under_test.state.queue_pool.queue_size = fake_size  # type: ignore[method-assign]

    # GET /recordings is not protected.
    r = await async_client.get("/recordings")
    assert r.status_code == 200

    # Even GET to a replay-shaped URL is not protected — only POST is.
    r2 = await async_client.get("/medallion/status")
    assert r2.status_code == 200
