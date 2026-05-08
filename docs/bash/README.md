# docs/bash — Command Reference

Key commands used before, during, and after making code changes.

| File | Phase | Purpose |
|------|-------|---------|
| [00-setup.sh](00-setup.sh) | Once | Environment bootstrap — `uv sync`, Playwright install, version checks |
| [01-explore.sh](01-explore.sh) | Before | Orient — directory listings, git state, CLI help, plan docs |
| [02-impact-analysis.sh](02-impact-analysis.sh) | Before | GitNexus impact analysis — **required before editing any symbol** |
| [03-lint.sh](03-lint.sh) | During | `ruff format` and `ruff check` — format, lint, auto-fix |
| [04-typecheck.sh](04-typecheck.sh) | During | `mypy` strict — full project or targeted module |
| [05-test.sh](05-test.sh) | During / After | `pytest` — markers, single tests, coverage, Playwright flags |
| [06-check.sh](06-check.sh) | After | Full gate — format → lint → typecheck → test (mirrors Stop hook) |
| [07-run-app.sh](07-run-app.sh) | After | Exercise CLI and FastAPI server |
| [08-git-workflow.sh](08-git-workflow.sh) | After | Git state, staging, committing (no Claude attribution) |
| [09-deps.sh](09-deps.sh) | Any | `uv add/remove/sync/upgrade` — dependency management |
| [10-playwright.sh](10-playwright.sh) | Debug | Playwright codegen, trace viewer, screenshot, headed test runs |
| [11-data-inspect.sh](11-data-inspect.sh) | Debug | Bronze artifact inspection, SQLite queries, disk usage |

## Typical workflow

```
01-explore      → understand current state
02-impact       → blast radius before editing
  [edit code]
03-lint         → fix style issues as you go
04-typecheck    → fix type errors as you go
05-test         → targeted tests while iterating
06-check        → full gate before declaring done
08-git-workflow → stage, detect_changes(), commit
```

## Key rules

- **Never hand-edit `pyproject.toml`** — use `uv add` / `uv remove` (see `09-deps.sh`).
- **Never commit without running `gitnexus_detect_changes()`** (see `02-impact-analysis.sh`).
- **Never add `Co-Authored-By: Claude`** to commits (see `08-git-workflow.sh`).
- **Stop hook** runs `ruff + mypy + pytest` automatically on task completion — `06-check.sh` is the manual equivalent.
- **PostToolUse hook** auto-formats on every file edit — `03-lint.sh` is the manual equivalent.
