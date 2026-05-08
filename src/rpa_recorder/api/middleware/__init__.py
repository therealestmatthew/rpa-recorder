"""Middleware registry — outermost first."""

from typing import TYPE_CHECKING, Any

from rpa_recorder.api.middleware.backpressure import BackpressureMiddleware
from rpa_recorder.api.middleware.rate_limit import RateLimitMiddleware
from rpa_recorder.api.middleware.request_id import RequestIdMiddleware
from rpa_recorder.api.middleware.structured_logging import StructuredLoggingMiddleware

if TYPE_CHECKING:
    from starlette.middleware.base import BaseHTTPMiddleware


def default_middleware_stack(
    *,
    rate_limit_per_minute: int = 60,
    backpressure_paths: tuple[str, ...] = ("/recordings/{rid}/replay",),
    backpressure_queue: str = "replay_queue",
    max_queue_depth: int = 100,
) -> list[tuple[type[BaseHTTPMiddleware], dict[str, Any]]]:
    """Ordered list registered into FastAPI. Outermost first.

    Order rationale:
      1. RequestId — assigns X-Request-ID before logging needs it.
      2. StructuredLogging — binds structlog contextvars per request.
      3. RateLimit — per-IP token bucket; 429 before doing work.
      4. Backpressure — only on enqueueing routes; 429 if queue saturated.
    """
    return [
        (RequestIdMiddleware, {}),
        (StructuredLoggingMiddleware, {}),
        (RateLimitMiddleware, {"per_minute": rate_limit_per_minute}),
        (
            BackpressureMiddleware,
            {
                "protected_paths": backpressure_paths,
                "queue_name": backpressure_queue,
                "max_depth": max_queue_depth,
            },
        ),
    ]


__all__ = [
    "BackpressureMiddleware",
    "RateLimitMiddleware",
    "RequestIdMiddleware",
    "StructuredLoggingMiddleware",
    "default_middleware_stack",
]
