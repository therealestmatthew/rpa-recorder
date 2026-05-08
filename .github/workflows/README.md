# Workflows

CI for `rpa-recorder`. Modular, marker-sharded, fail-fast.

## Pipelines

| File | Trigger | Purpose |
|---|---|---|
| `ci.yml` | push to `main`, every PR, manual | Six-job pipeline gating merges |
| `llm-tests.yml` | Mondays 09:00 UTC, manual | Cost-bearing tests against the Anthropic API |

## Job graph (`ci.yml`)

```
lint  ──┐
        ├──> unit (matrix: ubuntu, macos) ──┬──> integration ──┐
typecheck ─┘                                 └──> worker ──────┴──> coverage
```

Cheap jobs (`lint`, `typecheck`) gate the expensive jobs. `integration` and `worker` run in parallel after `unit` succeeds. `coverage` aggregates artifacts from all three test jobs.

## Test markers

Defined in `pyproject.toml` `[tool.pytest.ini_options].markers`:

| Marker | Meaning | Job |
|---|---|---|
| (none) | unit test, no external deps | `unit` |
| `slow` | takes >10 s | excluded by default; opt-in via `pytest -m slow` |
| `integration` | needs a real Chromium via Playwright | `integration` (ubuntu only) |
| `worker` | needs a Redis service | `worker` (ubuntu only) |
| `llm` | makes Anthropic API calls (costs money) | gated to `llm-tests.yml` |

### Dual-marker pattern

Tests that need both Playwright and Redis (e.g., `tests/test_api_e2e.py` once it exists) should be marked `@pytest.mark.integration` AND `@pytest.mark.worker`. They run only in the `worker` job (which has both browser via `setup-browser` and Redis via the service container). The `integration` job's filter is `integration and not llm and not worker` so the dual-marked tests don't run twice.

### Adding a new category

Three steps to add a `postgres` (or any other) job:

1. Register the marker in `pyproject.toml` `[tool.pytest.ini_options].markers`.
2. Add a job to `ci.yml` with the appropriate `services:` block.
3. Update each existing test job's `-m` filter to add `not <new-marker>` so the new tests don't run twice.

Composite actions (`setup-environment`, `setup-browser`) are reused unchanged.

## Required secrets

| Secret | Used by | Effect if missing |
|---|---|---|
| `CODECOV_TOKEN` | `coverage` job | Upload silently no-ops; `fail_ci_if_error: false` keeps CI green. Coverage XMLs still attach as workflow artifacts. |
| `ANTHROPIC_API_KEY` | `llm-tests.yml` | Workflow runs but tests fail at API call. The `if:` gate in `llm-tests.yml` only allows the schedule run or repo-owner manual triggers. |

Set them in **Settings → Secrets and variables → Actions**.

## Empty-collection grace

The `worker` job and `llm-tests.yml` both wrap pytest so that exit code 5 ("no tests collected") is treated as success. This makes the jobs go green from day one, before M11.5 (workers) and M9 (LLM) land. Once tests with those markers exist, the wrapper still runs them normally — the guard only matters when the collection is empty.

The trade-off: a future accidental deletion of all `worker` or `llm` tests would also pass silently. Audit `git diff` for marker churn during reviews.

## Caching

| Cache | Mechanism | Scope |
|---|---|---|
| uv (deps + Python) | `astral-sh/setup-uv@v3` with `enable-cache: true`, key on `uv.lock` hash | per-commit immutable |
| Playwright browsers | implicit `~/.cache/ms-playwright/`; `playwright install` is idempotent | invalidated on bump |

## Concurrency

`concurrency.group: ci-${{ github.ref }}` + `cancel-in-progress: true` cancels in-flight runs on the same branch when a newer commit pushes. Saves CI minutes during rapid PR iteration.

## OS support

Service containers (e.g., Redis) are Linux-only on GitHub Actions. The `worker` and `integration` jobs are Ubuntu-only. The `unit` matrix includes macOS to catch platform-specific issues (Pathlib quirks, encoding, etc.). Windows is **not** in the matrix in v1; the codebase aims at Windows (`.python-version` 3.14, ruff cross-platform) but no CI currently verifies it.

## Local debugging

- `uvx actionlint .github/workflows/*.yml` — validate workflow YAML
- `uv run pytest -m "worker and not llm"` — local run of a CI marker filter
- `act` (third-party) — execute workflows locally; not officially supported

## Concurrent-job slot limits

GitHub Actions free tier allows ~20 concurrent jobs per account. A burst of PRs can queue jobs. Expect wall-clock to grow under load.
