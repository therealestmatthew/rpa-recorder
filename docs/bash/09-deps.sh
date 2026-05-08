#!/usr/bin/env bash
# 09-deps.sh — uv dependency management
# NEVER hand-edit pyproject.toml for additions/removals — use uv commands.

# ── Install / sync ─────────────────────────────────────────────────────────────

# Sync all deps from uv.lock into .venv (safe to rerun)
uv sync

# ── Add packages ──────────────────────────────────────────────────────────────

# Add a runtime dependency
uv add httpx

# Add a dev/test-only dependency
uv add --dev factory-boy

# Add a package with an extra
uv add "anthropic[bedrock]"

# Add the optional postgres extra defined in pyproject.toml
uv sync --extra postgres

# ── Remove packages ────────────────────────────────────────────────────────────

uv remove httpx

# ── Upgrade packages ───────────────────────────────────────────────────────────

# Upgrade a single package (updates uv.lock)
uv lock --upgrade-package anthropic

# Upgrade all packages
uv lock --upgrade

# ── Inspect ────────────────────────────────────────────────────────────────────

# List all installed packages in the venv
uv pip list

# Show details for a specific package (version, deps, location)
uv pip show anthropic

# Show the dependency tree
uv pip tree

# Check for outdated packages
uv pip list --outdated

# ── Lock file ─────────────────────────────────────────────────────────────────

# Re-generate uv.lock without changing versions (resolves if out of sync)
uv lock
