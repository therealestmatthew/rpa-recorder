#!/usr/bin/env bash
# 05-test.sh — pytest test execution
# Coverage is enabled by default via addopts in pyproject.toml.
# filterwarnings = error — any warning fails the suite.

# ── Full suite ─────────────────────────────────────────────────────────────────

uv run pytest

# ── Marker filters ─────────────────────────────────────────────────────────────

# Skip slow tests (fastest feedback loop)
uv run pytest -m "not slow"

# Skip slow AND integration (no browser)
uv run pytest -m "not slow and not integration"

# Only real-browser integration tests
uv run pytest -m integration

# Only LLM tests (calls Anthropic API — costs money)
uv run pytest -m llm

# ── Target specific tests ──────────────────────────────────────────────────────

# Single test file
uv run pytest tests/test_heuristic_engine.py

# Single test function
uv run pytest tests/test_heuristic_engine.py::test_name

# Keyword filter (-k matches test name / class name)
uv run pytest -k "recovery"
uv run pytest -k "not llm"

# ── Failure control ────────────────────────────────────────────────────────────

# Stop on first failure
uv run pytest -x

# Stop on first failure, rerun only last-failed
uv run pytest -x --lf

# Rerun only last-failed tests
uv run pytest --lf

# Rerun last-failed first, then rest
uv run pytest --ff

# ── Output verbosity ───────────────────────────────────────────────────────────

# Verbose (show each test name)
uv run pytest -v

# Extra verbose (show print output)
uv run pytest -s

# Short traceback
uv run pytest --tb=short

# No traceback
uv run pytest --tb=no

# ── Coverage ───────────────────────────────────────────────────────────────────

# Default (terminal report, --cov=rpa_recorder is in addopts)
uv run pytest

# HTML coverage report (opens in browser)
uv run pytest --cov-report=html
# then: open htmlcov/index.html

# Coverage for a single module
uv run pytest --cov=rpa_recorder.recovery tests/test_recovery_engine.py

# ── Playwright-specific test flags ────────────────────────────────────────────
# See also 10-playwright.sh for browser debugging commands.

# Run browser tests in headed mode (visible browser window)
uv run pytest --headed -m integration

# Run browser tests with slow-motion (ms delay between actions)
uv run pytest --headed --slowmo 500 -m integration

# Capture Playwright traces for all tests (view with: playwright show-trace)
uv run pytest --tracing=on -m integration

# Capture traces only on failure
uv run pytest --tracing=retain-on-failure -m integration
