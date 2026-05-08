#!/usr/bin/env bash
# 02-impact-analysis.sh — GitNexus impact analysis before editing
# REQUIRED before modifying any function, class, or method.
# GitNexus MCP tools are called from Claude, not from bash — this file
# documents the invocation patterns and the CLI refresh command.

# ── GitNexus CLI (bash) ────────────────────────────────────────────────────────

# Re-index the repo if the MCP tools warn the index is stale
npx gitnexus analyze

# Check index status (symbol count, last analyzed timestamp)
npx gitnexus status

# Clean the index (use before a full re-analyze)
npx gitnexus clean

# Generate a wiki from the current index
npx gitnexus wiki

# List all indexed repos
npx gitnexus list

# ── GitNexus MCP tool patterns (Claude invocations) ───────────────────────────
# The tools below are called by Claude via the MCP server, not in bash.
# They are documented here as reference for the required pre-edit workflow.

# 1. BEFORE editing any symbol — blast radius analysis:
#    gitnexus_impact({ target: "SymbolName", direction: "upstream" })
#    Reports: direct callers, affected processes, risk level (LOW/MEDIUM/HIGH/CRITICAL)
#    MUST warn user and halt if HIGH or CRITICAL.

# 2. Full symbol context — callers, callees, execution flows:
#    gitnexus_context({ name: "SymbolName" })

# 3. Concept / keyword search — returns process-grouped results:
#    gitnexus_query({ query: "recovery strategy" })

# 4. BEFORE committing — verify change scope matches intent:
#    gitnexus_detect_changes()

# 5. Rename with call-graph awareness (never use find-and-replace):
#    gitnexus_rename({ from: "OldName", to: "NewName" })

# ── GitNexus MCP resources ────────────────────────────────────────────────────
# gitnexus://repo/rpa/context    — codebase overview, index freshness
# gitnexus://repo/rpa/clusters   — all functional areas
# gitnexus://repo/rpa/processes  — all execution flows
# gitnexus://repo/rpa/process/{name}  — step-by-step execution trace
