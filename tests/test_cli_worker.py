"""Tests for `rpa worker`."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from typer.testing import CliRunner

from rpa_recorder.cli.app import app


def _patch_arq(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Replace `arq.worker.create_worker` so the test never spawns Redis."""
    captured: dict[str, Any] = {}

    fake_worker = MagicMock()
    fake_worker.async_run = AsyncMock(return_value=None)

    def fake_create_worker(settings_cls: type) -> Any:
        captured["settings_cls"] = settings_cls
        return fake_worker

    import arq.worker  # noqa: PLC0415

    monkeypatch.setattr(arq.worker, "create_worker", fake_create_worker)
    return captured


def test_worker_replay_picks_replay_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    from rpa_recorder.workers.settings import ReplayWorkerSettings  # noqa: PLC0415

    captured = _patch_arq(monkeypatch)
    result = CliRunner().invoke(app, ["worker", "--queue", "replay"], catch_exceptions=False)

    assert result.exit_code == 0
    assert captured["settings_cls"] is ReplayWorkerSettings


def test_worker_medallion_picks_medallion_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    from rpa_recorder.workers.settings import MedallionWorkerSettings  # noqa: PLC0415

    captured = _patch_arq(monkeypatch)
    result = CliRunner().invoke(
        app, ["worker", "--queue", "medallion"], catch_exceptions=False
    )

    assert result.exit_code == 0
    assert captured["settings_cls"] is MedallionWorkerSettings


def test_worker_unknown_queue_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_arq(monkeypatch)
    result = CliRunner().invoke(
        app, ["worker", "--queue", "nope"], catch_exceptions=True
    )
    assert result.exit_code != 0
