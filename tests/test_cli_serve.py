"""Tests for `rpa serve`."""

import importlib
import types
from typing import TYPE_CHECKING, Any

from typer.testing import CliRunner

from rpa_recorder.cli.app import app

if TYPE_CHECKING:
    import pytest


def _patch_uvicorn(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Replace `importlib.import_module("uvicorn")` with a recording stub.

    The serve command lazy-loads uvicorn so `rpa --help` doesn't drag
    watchfiles/anyio onto the cold-start path. The stub captures the kwargs
    passed to `uvicorn.run` so tests can assert against them.
    """
    captured: dict[str, Any] = {}

    def fake_run(target: str, **kwargs: Any) -> None:
        captured["target"] = target
        captured.update(kwargs)

    fake_uvicorn = types.SimpleNamespace(run=fake_run)
    real_import = importlib.import_module

    def fake_import(name: str, package: str | None = None) -> Any:
        if name == "uvicorn":
            return fake_uvicorn
        return real_import(name, package)

    monkeypatch.setattr(importlib, "import_module", fake_import)
    return captured


def test_serve_invokes_uvicorn_run(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _patch_uvicorn(monkeypatch)

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["serve", "--host", "0.0.0.0", "--port", "9000"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    assert captured["target"] == "rpa_recorder.api.routes:app"
    assert captured["host"] == "0.0.0.0"
    assert captured["port"] == 9000
    assert captured["reload"] is False


def test_serve_reload_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _patch_uvicorn(monkeypatch)

    runner = CliRunner()
    result = runner.invoke(app, ["serve", "--reload"], catch_exceptions=False)
    assert result.exit_code == 0
    assert captured["reload"] is True
    assert captured["port"] == 8000
