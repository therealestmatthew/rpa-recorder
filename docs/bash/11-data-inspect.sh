#!/usr/bin/env bash
# 11-data-inspect.sh — inspect bronze artifacts and SQLite storage
# Bronze root: data/bronze/  (RPA_BRONZE_ROOT env var overrides)
# SQLite db:   rpa.db        (RPA_DATABASE_URL env var overrides)

# ── Bronze directory layout ────────────────────────────────────────────────────

# Top-level bronze structure
ls -la data/bronze/

# All recordings
ls -la data/bronze/recordings/

# Artifacts for a specific recording
ls -la "data/bronze/recordings/<uuid>/"

# All raw event files
find data/bronze/recordings -name "raw_events.jsonl" | sort

# All Playwright trace files
find data/bronze/recordings -name "trace.zip" | sort

# All network HAR files
find data/bronze/recordings -name "network.har" | sort

# LLM call envelopes
ls -la data/bronze/llm/

# Run attempt artifacts (screenshots, DOM snapshots, a11y trees)
find data/bronze/runs -type f | sort

# ── Bronze event inspection ────────────────────────────────────────────────────

# Stream raw events for a recording (one JSON envelope per line)
cat "data/bronze/recordings/<uuid>/raw_events.jsonl"

# Pretty-print the last 10 events
tail -n 10 "data/bronze/recordings/<uuid>/raw_events.jsonl" | python -m json.tool

# Count events in a recording
wc -l "data/bronze/recordings/<uuid>/raw_events.jsonl"

# Search events by type
grep '"type": "click"' "data/bronze/recordings/<uuid>/raw_events.jsonl"

# ── SQLite database inspection ────────────────────────────────────────────────
# Default db file: rpa.db (project root)

# List all tables
sqlite3 rpa.db ".tables"

# Schema for all tables
sqlite3 rpa.db ".schema"

# Recent recordings (newest first)
sqlite3 rpa.db "SELECT id, url, created_at FROM recordings ORDER BY created_at DESC LIMIT 20;"

# Recording count
sqlite3 rpa.db "SELECT COUNT(*) FROM recordings;"

# Actions for a specific recording
sqlite3 rpa.db "SELECT * FROM actions WHERE recording_id = '<uuid>' ORDER BY seq;"

# Replay runs
sqlite3 rpa.db "SELECT id, recording_id, status, created_at FROM runs ORDER BY created_at DESC LIMIT 20;"

# ── CLI-based inspection (preferred over raw sqlite3) ─────────────────────────

# List all recordings via CLI
uv run rpa list

# Show a specific recording's actions and metadata
uv run rpa show <recording-id>

# ── Disk usage ────────────────────────────────────────────────────────────────

# Total bronze layer size
du -sh data/bronze/

# Per-recording sizes (sorted largest first)
du -sh data/bronze/recordings/*/ 2>/dev/null | sort -rh | head -20

# LLM call storage
du -sh data/bronze/llm/
