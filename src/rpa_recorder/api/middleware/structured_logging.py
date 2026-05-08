"""Bind `request_id`, `method`, `path` into structlog contextvars per request."""

from typing import TYPE_CHECKING

import structlog
from starlette.middleware.base import BaseHTTPMiddleware

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from starlette.requests import Request
    from starlette.responses import Response


class StructuredLoggingMiddleware(BaseHTTPMiddleware):
    """Bind per-request fields into structlog contextvars and clear after."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = getattr(request.state, "request_id", None)
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )
        try:
            return await call_next(request)
        finally:
            structlog.contextvars.unbind_contextvars("request_id", "method", "path")
