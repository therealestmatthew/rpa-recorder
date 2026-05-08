"""FastAPI app factory. Wires lifespan, middleware, and routers."""

from fastapi import FastAPI

from rpa_recorder.api.lifespan import lifespan
from rpa_recorder.api.middleware import default_middleware_stack
from rpa_recorder.api.routers import all_routers
from rpa_recorder.config import Config


def create_app(config: Config | None = None) -> FastAPI:
    """Construct a `FastAPI` instance ready to serve."""
    cfg = config or Config()
    app = FastAPI(
        title="rpa-recorder",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.config = cfg
    for mw_cls, kwargs in default_middleware_stack(
        rate_limit_per_minute=cfg.rate_limit_per_minute,
        max_queue_depth=cfg.max_queue_depth,
    ):
        app.add_middleware(mw_cls, **kwargs)  # type: ignore[arg-type]
    for router in all_routers():
        app.include_router(router)
    return app


app = create_app()


__all__ = ["app", "create_app"]
