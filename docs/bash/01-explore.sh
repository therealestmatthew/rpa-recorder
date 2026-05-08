#!/usr/bin/env bash
# 01-explore.sh — orient before editing
# Run at the start of a session to understand current state.

# ── Directory structure ────────────────────────────────────────────────────────
# Package layout
ls -la src/rpa_recorder/
ls -la src/rpa_recorder/browser/
ls -la src/rpa_recorder/classifier/
ls -la src/rpa_recorder/classifier/heuristic/
ls -la src/rpa_recorder/classifier/heuristic/filters/
ls -la src/rpa_recorder/classifier/heuristic/normalizers/
ls -la src/rpa_recorder/classifier/heuristic/classifiers/
ls -la src/rpa_recorder/recovery/
ls -la src/rpa_recorder/storage/
ls -la src/rpa_recorder/medallion/
ls -la src/rpa_recorder/models/
ls -la src/rpa_recorder/api/
ls -la src/rpa_recorder/cli/

# Test files
ls -la tests/

# All Python source files
find src/rpa_recorder -name "*.py" | sort
find tests -name "*.py" | sort

# ── Git state ──────────────────────────────────────────────────────────────────
git status
git branch --show-current
git log --oneline -20

# Staged and unstaged diffs
git diff
git diff --staged

# ── CLI help ───────────────────────────────────────────────────────────────────
uv run rpa --help
uv run rpa record --help
uv run rpa replay --help
uv run rpa classify --help
uv run rpa list --help
uv run rpa show --help
uv run rpa serve --help

# ── Milestone / plan context ───────────────────────────────────────────────────
# Read the canonical spec before structural decisions
cat .claude/plans/bootstrap.md

# NOTE: for symbol exploration, prefer GitNexus MCP tools over grep:
#   gitnexus_query({query: "concept"})       — find execution flows
#   gitnexus_context({name: "SymbolName"})   — callers, callees, flow membership
# See 02-impact-analysis.sh for full GitNexus reference.
