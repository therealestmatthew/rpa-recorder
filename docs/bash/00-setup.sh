#!/usr/bin/env bash
# 00-setup.sh — one-time environment bootstrap
# Run once after cloning, or after switching Python versions.

# Verify pinned Python version matches .python-version
cat .python-version

# Install / sync all deps from uv.lock into .venv
uv sync

# Install Playwright browser binaries (Chromium only by default)
uv run playwright install

# Install with system deps (Linux CI or fresh machines)
uv run playwright install --with-deps

# Confirm tool versions
uv --version
uv run python --version
uv run ruff --version
uv run mypy --version
uv run pytest --version

# Show all available Python versions managed by uv
uv python list

# Confirm the CLI entry point is wired up
uv run rpa --help
