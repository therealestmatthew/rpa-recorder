# mypy: disable-error-code="no-untyped-def, no-untyped-call, type-arg, unused-ignore, attr-defined, comparison-overlap, misc"
"""Tests for `queues.events.publish_progress` and `backfill_events`."""

import json

import pytest

from rpa_recorder.queues.events import backfill_events, publish_progress


@pytest.mark.asyncio
async def test_publish_progress_writes_pubsub_and_list(fake_redis):
    pubsub = fake_redis.pubsub()
    await pubsub.subscribe("run:abc")

    await publish_progress(fake_redis, "abc", {"type": "action_started", "run_id": "abc"})

    listed = await fake_redis.lrange("events:abc", 0, -1)
    assert len(listed) == 1
    parsed = json.loads(listed[0])
    assert parsed["type"] == "action_started"
    assert "event_id" in parsed
    assert "ts" in parsed

    await pubsub.aclose()


@pytest.mark.asyncio
async def test_publish_progress_trims_list_to_buffer(fake_redis):
    for i in range(10):
        await publish_progress(fake_redis, "abc", {"type": "tick", "i": i}, buffer_size=5)

    listed = await fake_redis.lrange("events:abc", 0, -1)
    assert len(listed) == 5
    parsed = [json.loads(item) for item in listed]
    indices = [p["i"] for p in parsed]
    assert sorted(indices) == [5, 6, 7, 8, 9]


@pytest.mark.asyncio
async def test_publish_progress_preserves_explicit_event_id(fake_redis):
    await publish_progress(fake_redis, "abc", {"type": "x", "event_id": "preset-123"})
    listed = await fake_redis.lrange("events:abc", 0, -1)
    parsed = json.loads(listed[0])
    assert parsed["event_id"] == "preset-123"


@pytest.mark.asyncio
async def test_backfill_events_returns_chronological_order(fake_redis):
    for i in range(3):
        await publish_progress(fake_redis, "abc", {"type": "tick", "i": i})

    backfilled = await backfill_events(fake_redis, "abc")
    indices = [b["i"] for b in backfilled]
    assert indices == [0, 1, 2]
