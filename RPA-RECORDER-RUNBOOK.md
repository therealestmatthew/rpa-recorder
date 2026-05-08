# rpa-recorder runbook

Operational guide for the `rpa` CLI. Six subcommands: `record`, `list`, `show`, `classify`, `replay`, `serve`. The canonical reference for any signature is `--help` on the command itself.

## Setup (one-time)

```powershell
uv sync                       # install deps from uv.lock into .venv
uv run playwright install     # download browser binaries (required for record/replay)
```

Optional: copy `.env.example` to `.env` and set `RPA_ANTHROPIC_API_KEY` if you plan to use the LLM classifier path.

## Entrypoints (all equivalent)

```powershell
uv run rpa <cmd> ...                     # installed console script
uv run python run.py <cmd> ...           # project-root entry
uv run python -m rpa_recorder <cmd> ...  # module entry via __main__.py shim
```

The runbook uses `uv run python run.py` below; substitute whichever entry you prefer.

---

## `record` — capture a session

Opens a Chromium window, records every interaction, persists on `Ctrl+C`.

```powershell
uv run python run.py record <NAME> --url <URL> [--headless]
```

| Slot | Required | Notes |
|------|----------|-------|
| `NAME` (positional) | yes | Free-form label, e.g. `google-search`, `okta-login`. |
| `--url` | yes | **Must include scheme.** `https://google.com`, not `google.com`. |
| `--headless` | no | Omit for a visible browser. Recommended for first-time recording. |

**Examples:**
```powershell
uv run python run.py record google-search --url https://google.com
uv run python run.py record okta-login --url https://example.okta.com --headless
```

End the session with `Ctrl+C`. The CLI prints `Saved recording <UUID>` and exits with code 130 (SIGINT convention). The recording lives in the SQLite DB; raw artifacts also land in `data/bronze/recordings/<UUID>/`.

---

## `list` — see your recordings

```powershell
uv run python run.py list
```

Newest-first table with UUID, name, URL, and timestamp. Copy the UUID for downstream commands.

---

## `show` — inspect a recording

```powershell
uv run python run.py show <RECORDING_ID>
uv run python run.py show <RECORDING_ID> --no-redact   # unmask sensitive inputs
```

`RECORDING_ID` must be the full UUID from `list` — no prefix matching. Default is `--redact` (values on inputs marked `is_sensitive` are masked).

---

## `classify` — re-run heuristic classification

```powershell
uv run python run.py classify <RECORDING_ID>
```

Runs the filter → normalize → classify pipeline ([src/rpa_recorder/classifier/heuristic/engine.py](src/rpa_recorder/classifier/heuristic/engine.py)) over a saved recording without launching a browser. Useful after editing rules under `classifier/heuristic/`.

---

## `replay` — execute a recording

```powershell
uv run python run.py replay <RECORDING_ID> [--headless]
uv run python run.py replay <RECORDING_ID> --param query=hello --param limit=10
```

`--param key=value` is repeatable for parameter substitution (binds to `ParameterDef`s captured at record time).

---

## `serve` — FastAPI control plane

```powershell
uv run python run.py serve                              # 127.0.0.1:8000
uv run python run.py serve --host 0.0.0.0 --port 9000
uv run python run.py serve --reload                     # dev: auto-reload on edits
```

Mounts the routes from [src/rpa_recorder/api/routes.py](src/rpa_recorder/api/routes.py) under uvicorn.

---

## End-to-end smoke test

```powershell
uv run python run.py record demo --url https://example.com   # interact, then Ctrl+C
uv run python run.py list                                    # copy the UUID
uv run python run.py show <UUID>
uv run python run.py classify <UUID>
uv run python run.py replay <UUID> --headless
```

---

## Storage layout

| Path | Contents |
|------|----------|
| `rpa.db` | SQLite database — recordings, actions, runs, bronze pointers. Configurable via `RPA_DATABASE_URL`. |
| `data/bronze/recordings/<UUID>/` | Raw event JSONL per recording (medallion bronze tier). |
| `screenshots/`, `traces/`, `dom/`, `storage_state/` | Per-run artifact directories. |

All paths are configurable via `RPA_`-prefixed env vars — see [src/rpa_recorder/config.py](src/rpa_recorder/config.py) for the full list.

---

## Common gotchas

- **`Missing argument 'NAME'`** — `record` needs a positional name. `record demo --url https://...`.
- **`Missing option '--url'`** — `--url` value must include the scheme (`https://...`).
- **`Ctrl+C` is the only stop signal** for `record` — there's no `--duration` flag. The browser stays open until you interrupt.
- **`list` returns nothing after recording** — make sure you let `record` reach its `Saved recording <UUID>` line before killing the process. If you `Ctrl+C` twice or kill the terminal, the transaction rolls back. (Single `Ctrl+C` is the supported clean stop.)
- **Recording IDs are full UUIDs** — copy them out of `list`; no short-prefix matching.
- **Browser launch fails** — first-run only: `uv run playwright install`.
- **Working directory matters** — `rpa.db` and `data/` are resolved relative to the cwd unless overridden by env vars. Run from the project root, or set `RPA_DATABASE_URL` explicitly.

---

## Dev workflow

```powershell
uv run pytest                  # full suite (with coverage)
uv run pytest -m "not slow"    # skip slow tests
uv run ruff check .            # lint
uv run ruff format .           # format
uv run mypy .                  # strict type check
```

Slash commands wired in `.claude/commands/`: `/lint`, `/format`, `/typecheck`, `/test`, `/check`, `/milestone-status`. The Stop hook gates `ruff` + `mypy` + `pytest` before Claude declares done.
