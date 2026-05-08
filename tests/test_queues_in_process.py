# mypy: disable-error-code="no-untyped-def, no-untyped-call, type-arg, unused-ignore, attr-defined, comparison-overlap, misc"
"""Tests for `queues.in_process.InProcessQueuePool`."""

import asyncio

import pytest

from rpa_recorder.queues import InProcessQueuePool


@pytest.mark.asyncio
async def test_enqueue_runs_handler_and_returns_job_id(fake_redis):
    seen: list[dict] = []

    async def handler(_pool, **kwargs):
        seen.append(kwargs)

    pool = InProcessQueuePool(redis=fake_redis, registry={"replay_run": handler})
    try:
        result = await pool.enqueue_job("replay_run", run_id="r1", recording_id="rec1")
        assert result.status == "queued"
        assert result.job_id
        # Wait for the task to complete.
        await asyncio.sleep(0.05)
        assert len(seen) == 1
        assert seen[0]["run_id"] == "r1"
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_enqueue_unknown_function_raises(fake_redis):
    pool = InProcessQueuePool(redis=fake_redis, registry={})
    try:
        with pytest.raises(KeyError):
            await pool.enqueue_job("nope")
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_enqueue_unknown_queue_raises(fake_redis):
    async def handler(_pool, **_kw):
        return None

    pool = InProcessQueuePool(redis=fake_redis, registry={"replay_run": handler})
    try:
        with pytest.raises(ValueError, match="unknown queue"):
            await pool.enqueue_job("replay_run", _queue_name="bogus")
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_queue_size_reflects_active_jobs(fake_redis):
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_handler(_pool, **_kw):
        started.set()
        await release.wait()

    pool = InProcessQueuePool(redis=fake_redis, registry={"replay_run": slow_handler})
    try:
        await pool.enqueue_job("replay_run", run_id="r1")
        await asyncio.wait_for(started.wait(), timeout=1.0)
        depth = await pool.queue_size("replay_queue")
        assert depth == 1
        release.set()
        await asyncio.sleep(0.05)
        assert await pool.queue_size("replay_queue") == 0
    finally:
        release.set()
        await pool.close()


@pytest.mark.asyncio
async def test_semaphore_caps_concurrency_per_queue(fake_redis):
    counter = {"active": 0, "max": 0}
    release = asyncio.Event()

    async def handler(_pool, **_kw):
        counter["active"] += 1
        counter["max"] = max(counter["max"], counter["active"])
        await release.wait()
        counter["active"] -= 1

    pool = InProcessQueuePool(
        redis=fake_redis,
        registry={"replay_run": handler},
        queue_limits={"replay_queue": 2},
    )
    try:
        for _ in range(5):
            await pool.enqueue_job("replay_run", run_id="x")
        await asyncio.sleep(0.05)
        assert counter["max"] <= 2
    finally:
        release.set()
        await pool.close()


@pytest.mark.asyncio
async def test_cancel_sets_redis_flag_and_signals_event(fake_redis):
    saw_cancelled = asyncio.Event()

    async def handler(pool, *, run_id: str):
        await asyncio.sleep(0.01)
        if pool.is_cancelled(run_id):
            saw_cancelled.set()

    pool = InProcessQueuePool(redis=fake_redis, registry={"replay_run": handler})
    try:
        await pool.enqueue_job("replay_run", run_id="r1")
        first = await pool.cancel("r1")
        await asyncio.sleep(0.05)
        assert first is True
        assert saw_cancelled.is_set()
        assert await fake_redis.get("cancel:r1") in (b"1", "1")
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_close_drains_active_tasks(fake_redis):
    started = asyncio.Event()
    finished = asyncio.Event()

    async def handler(_pool, **_kw):
        started.set()
        try:
            await asyncio.sleep(60)
        finally:
            finished.set()

    pool = InProcessQueuePool(
        redis=fake_redis,
        registry={"replay_run": handler},
        shutdown_grace_s=0.05,
    )
    await pool.enqueue_job("replay_run", run_id="r1")
    await asyncio.wait_for(started.wait(), timeout=1.0)
    await pool.close()
    assert finished.is_set()
