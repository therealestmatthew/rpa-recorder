#!/usr/bin/env bash
# 03-lint.sh — ruff format and lint
# PostToolUse hook auto-formats on every edit; run manually when needed.

# ── Format ─────────────────────────────────────────────────────────────────────

# Format entire project
uv run ruff format .

# Format a specific file or directory
uv run ruff format src/rpa_recorder/recovery/

# Check what would change without writing (dry-run)
uv run ruff format --check .

# ── Lint ───────────────────────────────────────────────────────────────────────

# Lint entire project (report only)
uv run ruff check .

# Lint and auto-fix safe violations
uv run ruff check --fix .

# Lint a specific file
uv run ruff check src/rpa_recorder/classifier/engine.py

# Lint and fix a specific directory
uv run ruff check --fix src/rpa_recorder/recovery/

# Show details about a specific rule code
uv run ruff rule S101

# Run only specific rule categories (e.g. security + pathlib)
uv run ruff check --select S,PTH .

# Ignore a rule for a one-off check
uv run ruff check --ignore S101 .

# ── Config reference ───────────────────────────────────────────────────────────
# line-length = 100, target-version = "py314"
# Active rule sets: S, PTH, PL, ASYNC, RUF (plus standard sets)
# Per-file ignores: cli/**  → B008 (Typer Option() defaults)
#                   tests/**→ S, ARG, PLR, ASYNC240
