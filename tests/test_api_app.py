# mypy: disable-error-code="no-untyped-def, no-untyped-call, type-arg, unused-ignore, attr-defined, comparison-overlap, misc"
"""Tests for `rpa_recorder.api.app.create_app` (M12)."""

from fastapi import FastAPI

from rpa_recorder.api.app import create_app
from rpa_recorder.api.middleware import (
    BackpressureMiddleware,
    RateLimitMiddleware,
    RequestIdMiddleware,
    StructuredLoggingMiddleware,
)


def test_create_app_returns_fastapi_with_routes():
    app = create_app()
    assert isinstance(app, FastAPI)
    paths = {route.path for route in app.routes}
    expected = {
        "/healthz",
        "/readyz",
        "/recordings",
        "/recordings/{rid}",
        "/runs",
        "/runs/{rid}",
        "/runs/{rid}/cancel",
        "/recordings/{rid}/replay",
        "/medallion/recompute",
        "/medallion/compact",
        "/medallion/status",
        "/runs/{rid}/stream",
    }
    missing = expected - paths
    assert not missing, f"missing routes: {missing}"


def test_create_app_registers_middleware_stack():
    app = create_app()
    classes = [m.cls for m in app.user_middleware]
    assert RequestIdMiddleware in classes
    assert StructuredLoggingMiddleware in classes
    assert RateLimitMiddleware in classes
    assert BackpressureMiddleware in classes
