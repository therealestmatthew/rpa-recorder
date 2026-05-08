"""`get_redis()` — returns the process-singleton Redis client from `app.state`."""

from typing import TYPE_CHECKING, cast

from fastapi import Request

if TYPE_CHECKING:
    from redis.asyncio import Redis


def get_redis(request: Request) -> Redis:
    """Return the Redis client constructed in `lifespan`."""

    return cast("Redis", request.app.state.redis)
