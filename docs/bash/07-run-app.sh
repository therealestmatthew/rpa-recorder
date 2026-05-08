#!/usr/bin/env bash
# 07-run-app.sh — exercise the CLI and API server
# Three equivalent entry points all resolve to rpa_recorder.cli:app.

# ── Entry points ───────────────────────────────────────────────────────────────

uv run rpa --help
uv run python run.py --help
uv run python -m rpa_recorder --help

# ── CLI commands ───────────────────────────────────────────────────────────────

# Start a recording session (opens browser)
uv run rpa record

# List all saved recordings
uv run rpa list

# Show details for a specific recording
uv run rpa show <recording-id>

# Classify actions in a recording (heuristic by default)
uv run rpa classify <recording-id>

# Classify using the LLM backend
uv run rpa classify --llm <recording-id>

# Replay a recording
uv run rpa replay <recording-id>

# Start the FastAPI HTTP server (default: http://127.0.0.1:8000)
uv run rpa serve

# ── FastAPI server ─────────────────────────────────────────────────────────────

# Serve with hot-reload during API development
uv run uvicorn rpa_recorder.api.routes:app --reload

# Serve on a custom host/port
uv run uvicorn rpa_recorder.api.routes:app --host 0.0.0.0 --port 8080 --reload

# API docs (after server is running)
# http://127.0.0.1:8000/docs       — Swagger UI
# http://127.0.0.1:8000/redoc      — ReDoc

# ── Quick Python checks ────────────────────────────────────────────────────────

# Import sanity check
uv run python -c "import rpa_recorder; print('ok')"

# Inspect config defaults
uv run python -c "from rpa_recorder.config import Config; import json; print(Config().model_dump_json(indent=2))"

# Drop into a REPL inside the venv
uv run python
