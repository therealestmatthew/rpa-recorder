#!/usr/bin/env bash
# 04-typecheck.sh — mypy strict type checking
# Runs in strict mode with the pydantic.mypy plugin.

# ── Full project typecheck ─────────────────────────────────────────────────────

uv run mypy .

# ── Targeted typecheck ─────────────────────────────────────────────────────────

# Single package
uv run mypy src/rpa_recorder/

# Single module
uv run mypy src/rpa_recorder/recovery/engine.py

# Single subpackage
uv run mypy src/rpa_recorder/classifier/

# ── Useful flags ───────────────────────────────────────────────────────────────

# Show error codes (useful when adding per-file ignores)
uv run mypy . --show-error-codes

# Show column numbers
uv run mypy . --show-column-numbers

# Pretty-print output
uv run mypy . --pretty

# Incremental cache info (diagnose stale cache issues)
uv run mypy . --verbose 2>&1 | grep -E "cache|stale"

# ── Config notes ───────────────────────────────────────────────────────────────
# strict = true; pydantic.mypy plugin enabled.
# Runtime-evaluated bases (BaseModel, BaseSettings, DeclarativeBase) use
# flake8-type-checking so their imports stay eager (not TYPE_CHECKING-guarded).
# Config lives in pyproject.toml [tool.mypy].
