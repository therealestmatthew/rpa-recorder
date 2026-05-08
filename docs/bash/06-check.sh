#!/usr/bin/env bash
# 06-check.sh — full pre-done gate (mirrors the Stop hook)
# Equivalent to running /check or waiting for the Stop hook to fire.
# Run this before declaring a task complete.
# Sequence: format → lint → typecheck → test (stops on first failure).

set -e  # exit on first failure

echo "=== ruff format ==="
uv run ruff format .

echo "=== ruff check ==="
uv run ruff check .

echo "=== mypy ==="
uv run mypy .

echo "=== pytest ==="
uv run pytest

echo "=== all checks passed ==="
