#!/usr/bin/env bash
# 10-playwright.sh — Playwright browser debugging
# Core to rpa-recorder; used for recorder, executor, and integration tests.

# ── Install ────────────────────────────────────────────────────────────────────

# Install Chromium (default browser for this project)
uv run playwright install

# Install with OS-level system dependencies (Linux CI / fresh machines)
uv run playwright install --with-deps

# Install a specific browser
uv run playwright install firefox

# ── Code generation ────────────────────────────────────────────────────────────

# Launch a browser and generate selector/action code interactively
uv run playwright codegen https://example.com

# Generate code in Python (default)
uv run playwright codegen --target python https://example.com

# ── Trace inspection ──────────────────────────────────────────────────────────
# Traces are stored in data/bronze/recordings/<uuid>/trace.zip

# Open the Playwright trace viewer GUI for a specific trace
uv run playwright show-trace data/bronze/recordings/<uuid>/trace.zip

# Open a trace from the traces/ working dir
uv run playwright show-trace traces/<trace-file>.zip

# ── Screenshot ────────────────────────────────────────────────────────────────

# Take a quick screenshot of a URL (headless)
uv run playwright screenshot https://example.com screenshot.png

# Full-page screenshot
uv run playwright screenshot --full-page https://example.com screenshot.png

# ── Test execution with browser visibility ────────────────────────────────────
# (Also documented in 05-test.sh)

# Run integration tests with visible browser window
uv run pytest --headed -m integration

# Run with slow-motion delay (ms) — useful for watching what the executor does
uv run pytest --headed --slowmo 500 -m integration

# Capture traces for all browser tests
uv run pytest --tracing=on -m integration

# Capture traces only on failure (lower overhead)
uv run pytest --tracing=retain-on-failure -m integration

# ── Environment / version info ────────────────────────────────────────────────

uv run playwright --version

# List installed browsers
uv run python -c "from playwright.sync_api import sync_playwright; p = sync_playwright().start(); print(p.chromium.executable_path)"
