# rpa-recorder — new-machine setup

Step-by-step for getting a freshly-cloned `rpa-recorder` running on a new computer. Targets Windows (PowerShell) primarily; macOS/Linux notes at the end.

Time estimate: ~5 minutes (most of it is the Playwright browser download).

---

## 0. Prerequisites

| Tool | Why | How to check |
|------|-----|--------------|
| **Git** | Clone the repo | `git --version` |
| **uv** | Python toolchain + dependency manager | `uv --version` |
| (Python 3.14) | Runtime — installed automatically by `uv sync` | — |

You do **not** need to pre-install Python. `uv` reads `.python-version` (`3.14`) and downloads a matching interpreter on the first `uv sync`.

### Install uv

```powershell
# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Restart the shell so `uv` lands on `PATH`. Verify with `uv --version`.

---

## 1. Clone the repo

```powershell
git clone <repo-url> rpa
cd rpa
```

All subsequent commands run from the `rpa` project root.

---

## 2. Install Python deps

```powershell
uv sync
```

What this does:
- Downloads CPython 3.14 if not present (per `.python-version`).
- Creates `.venv/` in the project root.
- Installs every dependency pinned in `uv.lock` — runtime + the `dev` group (pytest, ruff, mypy, pre-commit, etc.).

Expected output ends with `Resolved N packages` and `Installed N packages`.

---

## 3. Install Playwright browsers

The Python wheel does not ship browser binaries. Install them once per machine:

```powershell
uv run playwright install
```

This downloads Chromium (and friends) into the OS-level Playwright cache (~400 MB). `record` and `replay` will fail with a "browser not found" error if you skip this step.

---

## 4. (Optional) Configure environment variables

The project reads optional config from `.env` in the project root, with the prefix `RPA_`. The file is git-ignored — create it as needed.

Common settings:

```dotenv
# .env  (project root — git-ignored)

# Required only if you use the LLM classifier path (M9+).
RPA_ANTHROPIC_API_KEY=sk-ant-...

# Defaults are fine for local dev — override only if you need to.
# RPA_DATABASE_URL=sqlite+aiosqlite:///rpa.db
# RPA_DEFAULT_HEADLESS=false
# RPA_BRONZE_ROOT=data/bronze
```

Full list of settings: [src/rpa_recorder/config.py](src/rpa_recorder/config.py). Environment variables override `.env` values at runtime.

---

## 5. (Optional) Install pre-commit hooks

The repo ships a `.pre-commit-config.yaml` covering ruff, mypy, and basic file hygiene. To run those automatically on every `git commit`:

```powershell
uv run pre-commit install
```

To run them once across the whole tree without committing:

```powershell
uv run pre-commit run --all-files
```

Skip this if you prefer to rely on the CI-equivalent `/check` slash command (or manual `ruff` + `mypy` + `pytest`) instead.

---

## 6. (Optional) Postgres extra

Default storage is SQLite (`rpa.db`), no setup required. If you need Postgres:

```powershell
uv sync --extra postgres
# then point RPA_DATABASE_URL at your instance, e.g.
# RPA_DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/rpa
```

---

## 7. Verify the install

Run the test suite (skipping browser-integration tests for the smoke pass):

```powershell
uv run pytest -m "not slow and not integration"
```

Expected: all green, ~25s on a modern laptop.

Lint + type-check:

```powershell
uv run ruff check .
uv run mypy .
```

Both should print "no issues". The combined `/check` slash command runs all three.

---

## 8. End-to-end smoke test

Confirm `record` → `list` → `show` → `replay` actually work:

```powershell
uv run python run.py record demo --url https://example.com
# Browser opens. Click around for a few seconds. Press Ctrl+C in the terminal.
# Expect: "Saved recording <UUID>"

uv run python run.py list                # demo recording shows up
uv run python run.py show <UUID>         # rows of recorded actions
uv run python run.py replay <UUID> --headless
```

If any of these fail, see the operational runbook: [RPA-RECORDER-RUNBOOK.md](RPA-RECORDER-RUNBOOK.md) (common gotchas section).

---

## Project layout cheat-sheet

```
rpa/
├── .python-version          # 3.14 — read by uv
├── pyproject.toml           # deps, ruff, mypy, pytest config
├── uv.lock                  # pinned dependency lockfile (commit changes)
├── .pre-commit-config.yaml  # ruff + mypy + hygiene hooks
├── run.py                   # project-root CLI entry
├── src/rpa_recorder/        # package source
├── tests/                   # pytest tests
├── docs/                    # design docs (incl. m13 CI plan)
├── rpa.db                   # local SQLite — git-ignored, created on first run
└── data/bronze/             # raw event JSONL — git-ignored
```

---

## macOS / Linux notes

Everything above works the same; substitute `bash`/`zsh` for PowerShell. The bash equivalents:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
git clone <repo-url> rpa && cd rpa
uv sync
uv run playwright install
uv run pytest -m "not slow and not integration"
uv run python run.py record demo --url https://example.com
```

The project is fully Unix-portable — paths use `pathlib`, the storage layer is `aiosqlite` by default, and there are no Windows-only system calls.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `uv: command not found` | Shell `PATH` not refreshed after install | Restart the shell, or `source ~/.bashrc` / open a new PowerShell |
| `uv sync` fails on Python 3.14 | uv too old to fetch 3.14 | `uv self update`, then retry |
| `record` errors with "Executable doesn't exist at …" | Playwright browsers not installed | `uv run playwright install` |
| `pytest` fails with `ModuleNotFoundError: rpa_recorder` | Editable install missing | `uv sync` (re-runs editable install) |
| `list` returns empty after a recording | Did not exit `record` cleanly with a single `Ctrl+C` | Re-record; let the "Saved recording …" line print before closing the terminal |
| Pre-commit hooks fail with mypy errors | Stale type cache | `uv run mypy --cache-fine .` then retry, or delete `.mypy_cache/` |
| Coverage HTML clutters working dir | Default pytest config writes `htmlcov/` | Already git-ignored. Delete freely. |
