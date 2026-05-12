# Contributing

Thanks for the interest. `rpa-recorder` is a single-operator portfolio
project, but contributions and bug reports are welcome. The notes below
cover the dev loop and the conventions that keep the project's quality
gates green.

## Dev loop

```bash
uv sync                          # install deps from uv.lock
uv run playwright install chromium  # one-time, ~150 MB
uv run rpa --help                # confirm CLI works
uv run pytest                    # full test suite (with coverage)
uv run ruff check . && uv run ruff format --check .
uv run mypy .                    # strict mode
```

The Stop hook (`.claude/hooks/check-stop.cmd`) runs ruff + mypy + pytest
and gates conversation completion. The PostToolUse hook
(`.claude/hooks/python-autofmt.cmd`) auto-formats and auto-fixes on
every edit.

For a faster inner loop while iterating on a single area:

```bash
uv run pytest tests/test_<area>.py -x         # stop on first failure
uv run pytest -m "not slow and not llm"       # skip slow + LLM tests
```

LLM-marked tests hit the real Anthropic API; they are skipped by default
unless `RPA_RUN_LLM_TESTS=1` and `ANTHROPIC_API_KEY` (or
`RPA_ANTHROPIC_API_KEY`) are set.

## Branching

Feature branches off `main`. Rebase before opening a PR — keep the
history linear. Don't merge `main` into the feature branch.

## Commit conventions

[Conventional Commits](https://www.conventionalcommits.org/).
Subject ≤72 chars, imperative mood. Body explains the *why*, not the
*what* — the diff already shows the what.

```
feat(classifier): add hybrid heuristic-LLM escalation
fix(recovery): bound recursion depth to Config.recovery_max_depth
docs(plans): add plan library index, template, and 3 ADRs
chore: bump pydantic to 2.13
```

**Never include Claude attribution.** No `Co-Authored-By: Claude`
trailer, no "🤖 Generated with Claude Code" footer, no any other
mention of LLM authorship. This is an explicit norm; see
[`CLAUDE.md`](CLAUDE.md).

## PR checklist

Before opening a PR, confirm:

- [ ] Tests added or updated for the change. Coverage on new code ≥85%.
- [ ] `uv run ruff check .` — clean.
- [ ] `uv run mypy .` — clean (strict mode).
- [ ] `uv run pytest` — green.
- [ ] If a milestone's scope changed, the corresponding `docs/m*.md` is
      updated. New milestones use [`./.claude/plans/TEMPLATE.md`](.claude/plans/TEMPLATE.md).
- [ ] If a `Config` field was added or changed, a row was added or
      updated in [`docs/configuration.md`](docs/configuration.md).
- [ ] If a new architectural seam landed, an ADR was added under
      [`./.claude/plans/adr/`](.claude/plans/adr/).
- [ ] No Claude attribution in commit messages or PR description.

## Local dev with Redis

The default `Config.queue_backend` is `in_process`, so you can develop
without Redis. To exercise the production path:

```bash
docker compose up -d redis
export RPA_QUEUE_BACKEND=arq
uv run rpa worker --queue replay     # one terminal
uv run rpa worker --queue medallion  # another terminal
uv run rpa serve                     # FastAPI control plane
```

`docker compose down -v` to clean up.

## Running LLM tests locally

```bash
export RPA_ANTHROPIC_API_KEY=sk-ant-...
export RPA_RUN_LLM_TESTS=1
uv run pytest -m llm
```

Without those, LLM-marked tests are silently skipped. CI runs LLM tests
on a separate job that injects `ANTHROPIC_API_KEY` from a repo secret.

## Adding a new milestone

Copy [`./.claude/plans/TEMPLATE.md`](.claude/plans/TEMPLATE.md) to
`docs/m<N>-<slug>.md`. Required sections are listed there. Add a row to
the sequence table in [`docs/build-plan.md`](docs/build-plan.md). Same
shape as M1–M14.

## Code style notes

- This project does **not** use `from __future__ import annotations`.
  Runtime-needed types stay runtime-imported; type-only imports go
  under `if TYPE_CHECKING:`.
- Don't catch bare `except Exception:` unless you log and re-raise.
  `except:` (PEP 758 except-paren behavior in 3.14) is also a no-go.
- Async first. Sync libraries that block (DuckDB, heavy pyarrow) wrap
  in `asyncio.to_thread`.
- Pydantic v2 with `ConfigDict(strict=True, frozen=True)` for read-only
  models.
- ruff line length is 100.

## Reporting issues

Bugs and feature ideas as GitHub issues. Security findings via the
process in [`SECURITY.md`](SECURITY.md) — not via public issue.
