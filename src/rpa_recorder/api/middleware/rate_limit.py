"""Redis-backed token bucket per client IP."""

import time
from typing import TYPE_CHECKING, cast

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from redis.asyncio import Redis
    from starlette.requests import Request
    from starlette.responses import Response
    from starlette.types import ASGIApp


_log = structlog.get_logger(__name__)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """One-minute fixed window per IP.

    `INCR` + `EXPIRE 60` in a pipeline. Above `per_minute`, returns 429 with
    `Retry-After` set to the seconds remaining in the current minute window.
    """

    def __init__(self, app: ASGIApp, *, per_minute: int = 60) -> None:
        super().__init__(app)
        self._per_minute = per_minute

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        redis = self._redis_or_none(request)
        if redis is None:
            return await call_next(request)
        client = request.client
        ip = client.host if client is not None else "unknown"
        bucket = int(time.time() // 60)
        key = f"ratelimit:{ip}:{bucket}"
        try:
            async with redis.pipeline(transaction=False) as pipe:
                pipe.incr(key)
                pipe.expire(key, 60)
                results = await pipe.execute()
            count = int(results[0])
        except Exception as exc:
            _log.warning("rate_limit_redis_failed", error=str(exc), ip=ip)
            return await call_next(request)
        if count > self._per_minute:
            retry_after = 60 - int(time.time() % 60)
            return JSONResponse(
                {"error": "rate_limited", "detail": {"retry_after_s": retry_after}},
                status_code=429,
                headers={"Retry-After": str(retry_after)},
            )
        return await call_next(request)

    @staticmethod
    def _redis_or_none(request: Request) -> Redis | None:

        redis = getattr(request.app.state, "redis", None)
        return cast("Redis | None", redis)
