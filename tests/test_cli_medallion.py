"""Tests for `rpa medallion <subcommand>`."""

from pathlib import Path
from uuid import uuid4

import pytest
from typer.testing import CliRunner

from rpa_recorder.cli.app import app
from rpa_recorder.config import Config


@pytest.fixture
def isolated_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Config:
    """Force Config() to point at tmp_path so commands don't touch the real DB."""
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'rpa.db'}"
    bronze = tmp_path / "bronze"
    cold = tmp_path / "gold_cold"
    monkeypatch.setenv("RPA_DATABASE_URL", db_url)
    monkeypatch.setenv("RPA_BRONZE_ROOT", str(bronze))
    monkeypatch.setenv("RPA_GOLD_COLD_ROOT", str(cold))
    return Config()


def test_medallion_help_shows_subcommands(isolated_config: Config) -> None:
    result = CliRunner().invoke(app, ["medallion", "--help"], catch_exceptions=False)
    assert result.exit_code == 0
    output = result.stdout
    assert "promote" in output
    assert "compact" in output
    assert "prune" in output
    assert "status" in output


def test_medallion_compact_runs_against_empty_store(isolated_config: Config) -> None:
    """compact on a fresh store writes zero parquets and exits cleanly."""
    result = CliRunner().invoke(app, ["medallion", "compact"], catch_exceptions=False)
    assert result.exit_code == 0
    assert "wrote 0 parquet files" in result.stdout


def test_medallion_prune_dry_run_reports(isolated_config: Config) -> None:
    """prune --dry-run on a fresh store reports zero deletions."""
    result = CliRunner().invoke(
        app, ["medallion", "prune", "--dry-run"], catch_exceptions=False
    )
    assert result.exit_code == 0
    assert "would delete 0" in result.stdout


def test_medallion_status_lists_zero_artifacts(isolated_config: Config) -> None:
    result = CliRunner().invoke(app, ["medallion", "status"], catch_exceptions=False)
    assert result.exit_code == 0
    assert "bronze artifacts by kind:" in result.stdout


def test_medallion_promote_silver_requires_recording(isolated_config: Config) -> None:
    """`promote --layer silver` without `--recording` fails."""
    result = CliRunner().invoke(
        app, ["medallion", "promote", "--layer", "silver"], catch_exceptions=False
    )
    assert result.exit_code != 0


def test_medallion_promote_unknown_layer_errors(isolated_config: Config) -> None:
    result = CliRunner().invoke(
        app,
        ["medallion", "promote", "--layer", "platinum"],
        catch_exceptions=False,
    )
    assert result.exit_code != 0


def test_medallion_promote_gold_runs_on_empty_db(isolated_config: Config) -> None:
    """gold promotion on an empty DB walks zero recordings cleanly."""
    result = CliRunner().invoke(
        app, ["medallion", "promote", "--layer", "gold"], catch_exceptions=False
    )
    assert result.exit_code == 0
    assert "0 hot upserts" in result.stdout


def test_medallion_promote_gold_per_recording(
    isolated_config: Config, tmp_path: Path
) -> None:
    """gold promotion with `--recording` recomputes that recording's replay script."""
    rec_id = str(uuid4())
    result = CliRunner().invoke(
        app,
        ["medallion", "promote", "--layer", "gold", "--recording", rec_id],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
