"""Return 429 when the queue is saturated, only on protected paths."""

import re
from typing import TYPE_CHECKING, cast

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from starlette.requests import Request
    from starlette.responses import Response
    from starlette.types import ASGIApp

    from rpa_recorder.queues import QueuePool


_log = structlog.get_logger(__name__)


def _path_to_regex(template: str) -> re.Pattern[str]:
    """Convert a `/recordings/{rid}/replay`-style template to a regex."""
    pattern = re.sub(r"\{[^}]+\}", r"[^/]+", template)
    return re.compile(f"^{pattern}$")


class BackpressureMiddleware(BaseHTTPMiddleware):
    """Reject new replays with 429 if `pool.queue_size(...) > max_depth`."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        protected_paths: tuple[str, ...] = ("/recordings/{rid}/replay",),
        queue_name: str = "replay_queue",
        max_depth: int = 100,
        retry_after_s: int = 30,
    ) -> None:
        super().__init__(app)
        self._patterns = [_path_to_regex(p) for p in protected_paths]
        self._queue_name = queue_name
        self._max_depth = max_depth
        self._retry_after_s = retry_after_s

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if request.method != "POST" or not self._is_protected(request.url.path):
            return await call_next(request)
        pool = self._pool_or_none(request)
        if pool is None:
            return await call_next(request)
        try:
            depth = await pool.queue_size(self._queue_name)
        except Exception as exc:
            _log.warning("backpressure_queue_size_failed", error=str(exc))
            return await call_next(request)
        if depth > self._max_depth:
            return JSONResponse(
                {
                    "error": "queue_saturated",
                    "detail": {
                        "queue": self._queue_name,
                        "depth": depth,
                        "max_depth": self._max_depth,
                    },
                },
                status_code=429,
                headers={"Retry-After": str(self._retry_after_s)},
            )
        return await call_next(request)

    def _is_protected(self, path: str) -> bool:
        return any(p.match(path) for p in self._patterns)

    @staticmethod
    def _pool_or_none(request: Request) -> QueuePool | None:
        pool = getattr(request.app.state, "queue_pool", None)
        return cast("QueuePool | None", pool)
