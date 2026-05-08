"""Assign / propagate `X-Request-ID` per request."""

from typing import TYPE_CHECKING
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from starlette.requests import Request
    from starlette.responses import Response


HEADER = "x-request-id"


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Read inbound `X-Request-ID` (or mint one) and echo it on the response."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request.headers.get(HEADER) or uuid4().hex
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers[HEADER] = request_id
        return response
