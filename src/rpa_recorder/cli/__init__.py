"""Typer-driven CLI package.

The single attribute exposed here is `app`, the root `typer.Typer` constructed
in `app.py`. The console-script entry in `pyproject.toml` resolves to
`rpa_recorder.cli:app` — that is, this module's `app`.
"""

from rpa_recorder.cli.app import app

__all__ = ["app"]
