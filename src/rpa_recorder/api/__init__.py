"""FastAPI control plane (M12). Use `rpa serve` to start uvicorn against `app`."""

from rpa_recorder.api.app import app, create_app

__all__ = ["app", "create_app"]
