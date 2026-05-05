# M1 — Project scaffold

**Status:** completed

**Commits:** `c3fb36c chore: initial uv project scaffold`, `9729ae0 chore: scaffold src/rpa_recorder layout per spec`

**Source:** original spec at `.claude/plans/bootstrap.md`.

## Goal

A working Python 3.14 project skeleton with toolchain green: `uv sync`, `uv run pytest`, `uv run ruff check`, `uv run mypy .` all pass. Empty stubs for every module called out in the spec layout, so later milestones can fill them in without restructuring.

## What shipped

### `pyproject.toml`

- `name = "rpa-recorder"`, `version = "0.1.0"`, `requires-python = ">=3.14"`, MIT license, author Matthew Mulé.
- Runtime dependencies: `playwright`, `pydantic`, `pydantic-settings`, `fastapi`, `uvicorn[standard]`, `typer`, `sqlalchemy`, `aiosqlite`, `anthropic`, `structlog`, `rich`.
- Optional `postgres` extra: `asyncpg`.
- Dev group: `pytest`, `pytest-asyncio`, `pytest-cov`, `pytest-playwright`, `ruff`, `mypy`, `types-setuptools`, `pre-commit`.
- Console script: `rpa = "rpa_recorder.cli:app"`.
- Build: `hatchling` with `packages = ["src/rpa_recorder"]`.
- Ruff: `target-version = "py314"`, `line-length = 100`, selects `E,W,F,I,B,C4,UP,N,SIM,RUF,ASYNC,S,PTH,TCH,PL,RET,ARG,ERA`. `runtime-evaluated-base-classes` was extended in M5 to cover `pydantic_settings.BaseSettings` and `sqlalchemy.orm.DeclarativeBase`.
- mypy strict, plugins `pydantic.mypy`.
- pytest: `asyncio_mode = "auto"`, `pythonpath = ["src"]`, custom markers `slow`, `integration`, `llm`.

### Repository layout

Created under `src/rpa_recorder/`:

```
__init__.py
__main__.py
cli.py                 (placeholder)
config.py              (placeholder; populated in M5)
models/                (filled in M2)
browser/
  session.py, recorder.py, executor.py
classifier/
  heuristic.py, llm.py
recovery/
  strategies.py
storage/
  db.py, repositories.py
api/
  routes.py
assets/
  recorder_inject.js   (filled in M4)
```

Tests scaffold under `tests/` with `conftest.py`, `test_smoke.py`, and a `fixtures/` directory.

### Other files

- `.python-version` pinned to `3.14`.
- `.gitignore` covering `.venv/`, `__pycache__/`, `dist/`, `htmlcov/`, plus `.claude/` and `CLAUDE.md` so the agent workspace stays local.
- `uv.lock` (managed by uv).

## Verification

```powershell
uv sync
uv run pytest                 # passes (empty smoke test)
uv run ruff check .
uv run mypy .
uv run rpa --help             # surfaces the typer placeholder
```

## Critical files

- `pyproject.toml`
- `.python-version`
- `.gitignore`
- `src/rpa_recorder/**/*.py` (stubs)
- `tests/conftest.py`, `tests/test_smoke.py`
