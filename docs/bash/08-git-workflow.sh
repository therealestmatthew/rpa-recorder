#!/usr/bin/env bash
# 08-git-workflow.sh — git workflow and pre-commit checks
# Run gitnexus_detect_changes() via MCP BEFORE committing.

# ── State inspection ───────────────────────────────────────────────────────────

git status
git branch --show-current
git log --oneline -20

# Unstaged changes
git diff

# Staged changes
git diff --staged

# All changes (staged + unstaged)
git diff HEAD

# ── Staging ────────────────────────────────────────────────────────────────────

# Stage specific files (prefer this over git add -A to avoid accidental inclusions)
git add src/rpa_recorder/recovery/engine.py
git add tests/test_recovery_engine.py

# Review what is staged before committing
git diff --staged

# ── Committing ─────────────────────────────────────────────────────────────────

# Standard commit (no Claude attribution — see working agreements in CLAUDE.md)
git commit -m "feat(recovery): add wait-and-retry strategy"

# NEVER add Co-Authored-By: Claude or any Claude attribution to commits.

# ── Branch management ─────────────────────────────────────────────────────────

git checkout -b feat/my-feature
git push -u origin feat/my-feature

# ── Pre-commit checklist ───────────────────────────────────────────────────────
# 1. Run gitnexus_detect_changes() via MCP — verify scope matches intent.
# 2. Run 06-check.sh (format + lint + typecheck + test).
# 3. Stage specific files (not git add -A).
# 4. Commit without Claude attribution.

# ── Stash / undo ──────────────────────────────────────────────────────────────

# Stash uncommitted changes
git stash
git stash pop

# Unstage a file (non-destructive)
git restore --staged src/rpa_recorder/config.py

# Discard unstaged changes to a file (destructive — confirm first)
git restore src/rpa_recorder/config.py
