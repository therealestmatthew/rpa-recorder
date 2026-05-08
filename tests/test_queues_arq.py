"""ArqQueuePool unit tests against fakeredis."""

from unittest.mock import AsyncMock

import pytest

from rpa_recorder.queues.arq import ArqQueuePool


@pytest.fixture
def arq_pool_mock() -> AsyncMock:
    pool = AsyncMock()
    pool.enqueue_job = AsyncMock()
    pool.close = AsyncMock()
    return pool


@pytest.mark.asyncio
async def test_queue_size_via_zcard(fake_redis, arq_pool_mock) -> None:
    """`queue_size` reads the Redis ZSET length."""
    await fake_redis.zadd("replay_queue", {"job-a": 1.0, "job-b": 2.0})
    pool = ArqQueuePool(redis=fake_redis, arq_pool=arq_pool_mock)

    size = await pool.queue_size("replay_queue")

    assert size == 2


@pytest.mark.asyncio
async def test_queue_size_returns_zero_for_empty(fake_redis, arq_pool_mock) -> None:
    pool = ArqQueuePool(redis=fake_redis, arq_pool=arq_pool_mock)
    assert await pool.queue_size("medallion_queue") == 0


@pytest.mark.asyncio
async def test_cancel_sets_redis_flag(fake_redis, arq_pool_mock) -> None:
    """First cancel returns True; second is a no-op (returns False)."""
    pool = ArqQueuePool(redis=fake_redis, arq_pool=arq_pool_mock)

    first = await pool.cancel("run-123")
    second = await pool.cancel("run-123")

    assert first is True
    assert second is False
    assert (await fake_redis.get("cancel:run-123")) == b"1"


@pytest.mark.asyncio
async def test_close_calls_through_to_arq_pool(fake_redis, arq_pool_mock) -> None:
    pool = ArqQueuePool(redis=fake_redis, arq_pool=arq_pool_mock)

    await pool.close()

    arq_pool_mock.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_close_is_idempotent(fake_redis, arq_pool_mock) -> None:
    pool = ArqQueuePool(redis=fake_redis, arq_pool=arq_pool_mock)
    await pool.close()
    await pool.close()
    assert arq_pool_mock.close.await_count == 1


@pytest.mark.asyncio
async def test_enqueue_returns_failed_when_arq_returns_none(
    fake_redis, arq_pool_mock
) -> None:
    """A None job from ARQ (e.g., dedup hit) surfaces as `failed` status."""
    arq_pool_mock.enqueue_job.return_value = None
    pool = ArqQueuePool(redis=fake_redis, arq_pool=arq_pool_mock)

    result = await pool.enqueue_job("replay_run", run_id="r1", recording_id="rec1")

    assert result.status == "failed"


@pytest.mark.asyncio
async def test_enqueue_after_close_raises(fake_redis, arq_pool_mock) -> None:
    pool = ArqQueuePool(redis=fake_redis, arq_pool=arq_pool_mock)
    await pool.close()
    with pytest.raises(RuntimeError, match="closed"):
        await pool.enqueue_job("replay_run", run_id="r")
