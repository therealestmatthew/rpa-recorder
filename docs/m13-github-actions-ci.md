# M13 — GitHub Actions CI (modular workflows + composite actions)

**Status:** pending

**Source:** [.claude/plans/bootstrap.md](../.claude/plans/bootstrap.md) §CI Requirements; [build-plan.md](build-plan.md) §Concurrency conventions; [m11.5-workers-and-medallion-promotion.md](m11.5-workers-and-medallion-promotion.md) for the Redis service contract; [m12-fastapi-control-plane.md](m12-fastapi-control-plane.md) for integration test surface. Replaces the original sketch with a multi-job pipeline that fails-fast on cheap checks, runs expensive jobs only when prerequisites pass, and segregates tests by marker (`not llm`, `integration`, `worker`) so CI cost stays bounded.

## Goal

A `.github/workflows/ci.yml` pipeline that runs on every push to `main` and every pull request, structured as multiple short jobs rather than one monolithic job:

| Job | Cost | Runs when | Markers |
|---|---|---|---|
| `lint` | ~30 s | always | — |
| `typecheck` | ~1 min | always (parallel with lint) | — |
| `unit` | ~2 min | after lint + typecheck pass | `not llm and not integration and not worker` |
| `integration` | ~5 min | after unit passes | `integration and not llm and not worker` |
| `worker` | ~3 min | after unit passes | `worker and not llm` |
| `coverage` | ~30 s | after unit + integration + worker pass | combines artifacts |

Plus reusable building blocks:

- `.github/actions/setup-environment/` — composite action: checkout → install uv → cache → `uv sync`.
- `.github/actions/setup-browser/` — composite: install Playwright browsers (Chromium only, with deps).
- `.github/workflows/llm-tests.yml` — weekly schedule running `@pytest.mark.llm` tests (cost-bearing; gated by repo secret).

The architecture means: adding a new test category = define a marker in `pyproject.toml` + add one new job in `ci.yml` that calls the existing composite actions. No edits to existing jobs.

## Files

### Create

- `.github/workflows/ci.yml` — primary CI pipeline
- `.github/workflows/llm-tests.yml` — weekly LLM test schedule (gated)
- `.github/workflows/README.md` — workflow conventions, secret setup, marker meanings
- `.github/actions/setup-environment/action.yml` — composite: checkout + uv + cache + sync
- `.github/actions/setup-browser/action.yml` — composite: Playwright Chromium install
- `.github/codecov.yml` — Codecov configuration (target coverage thresholds, ignored paths)
- `.github/dependabot.yml` — weekly dependency updates for `pip` (uv-managed) and `github-actions`

### Modify

- `pyproject.toml` — confirm markers in `[tool.pytest.ini_options].markers` cover `slow`, `integration`, `llm`, `worker` (M13 adds `worker` if not already there)
- `.gitignore` — already covers `.coverage`, `htmlcov/`; verify

## Workflow structure

### `.github/workflows/ci.yml`

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
  workflow_dispatch:

concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true

env:
  UV_CACHE_DIR: ~/.cache/uv
  PYTHONUNBUFFERED: "1"

jobs:
  lint:
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - uses: actions/checkout@v4
      - uses: ./.github/actions/setup-environment
      - run: uv run ruff check .
      - run: uv run ruff format --check .

  typecheck:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4
      - uses: ./.github/actions/setup-environment
      - run: uv run mypy src/ tests/

  unit:
    needs: [lint, typecheck]
    runs-on: ${{ matrix.os }}
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, macos-latest]
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4
      - uses: ./.github/actions/setup-environment
      - run: uv run pytest -m "not integration and not llm and not worker" --cov --cov-report=xml --cov-report=term
      - uses: actions/upload-artifact@v4
        with:
          name: coverage-unit-${{ matrix.os }}
          path: coverage.xml

  integration:
    needs: [unit]
    runs-on: ubuntu-latest
    timeout-minutes: 20
    steps:
      - uses: actions/checkout@v4
      - uses: ./.github/actions/setup-environment
      - uses: ./.github/actions/setup-browser
      - run: uv run pytest -m "integration and not llm and not worker" --cov --cov-report=xml
      - uses: actions/upload-artifact@v4
        with:
          name: coverage-integration
          path: coverage.xml

  worker:
    needs: [unit]
    runs-on: ubuntu-latest
    timeout-minutes: 15
    services:
      redis:
        image: redis:7-alpine
        ports: ["6379:6379"]
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 5s
          --health-timeout 3s
          --health-retries 10
    env:
      RPA_REDIS_URL: redis://localhost:6379/0
    steps:
      - uses: actions/checkout@v4
      - uses: ./.github/actions/setup-environment
      - uses: ./.github/actions/setup-browser    # some worker tests spawn BrowserSession
      - run: uv run pytest -m "worker and not llm" --cov --cov-report=xml
      - uses: actions/upload-artifact@v4
        with:
          name: coverage-worker
          path: coverage.xml

  coverage:
    needs: [unit, integration, worker]
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - uses: actions/checkout@v4
      - uses: actions/download-artifact@v4
        with:
          pattern: coverage-*
          merge-multiple: false
          path: coverage-artifacts/
      - uses: codecov/codecov-action@v4
        with:
          files: ./coverage-artifacts/coverage-unit-ubuntu-latest/coverage.xml,./coverage-artifacts/coverage-integration/coverage.xml,./coverage-artifacts/coverage-worker/coverage.xml
          token: ${{ secrets.CODECOV_TOKEN }}
          fail_ci_if_error: false
```

### `.github/workflows/llm-tests.yml`

```yaml
name: LLM tests

on:
  schedule:
    - cron: "0 9 * * 1"     # Mondays 09:00 UTC
  workflow_dispatch:

jobs:
  llm:
    if: ${{ github.repository_owner == github.actor || github.event_name == 'schedule' }}
    runs-on: ubuntu-latest
    timeout-minutes: 30
    steps:
      - uses: actions/checkout@v4
      - uses: ./.github/actions/setup-environment
      - run: uv run pytest -m "llm" --cov --cov-report=term
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          RPA_RUN_LLM_TESTS: "1"
```

### `.github/actions/setup-environment/action.yml`

```yaml
name: Setup environment
description: Checkout, install uv, restore cache, sync deps
runs:
  using: composite
  steps:
    - uses: astral-sh/setup-uv@v3
      with:
        enable-cache: true
        cache-dependency-glob: uv.lock
    - shell: bash
      run: uv sync --frozen
```

### `.github/actions/setup-browser/action.yml`

```yaml
name: Setup browser
description: Install Playwright Chromium with system deps
runs:
  using: composite
  steps:
    - shell: bash
      run: uv run playwright install --with-deps chromium
```

### `.github/codecov.yml`

```yaml
coverage:
  status:
    project:
      default:
        target: 80%
        threshold: 1%
    patch:
      default:
        target: 75%
ignore:
  - tests/
  - "src/rpa_recorder/page_scripts/**/*.js"
  - "src/rpa_recorder/__main__.py"
```

### `.github/dependabot.yml`

```yaml
version: 2
updates:
  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "weekly"
  - package-ecosystem: "pip"
    directory: "/"
    schedule:
      interval: "weekly"
```

## Behavior

### Job dependency graph

```
┌─────────┐   ┌───────────┐
│  lint   │   │ typecheck │
└────┬────┘   └─────┬─────┘
     └────────┬─────┘
              │
              ▼
         ┌────────┐
         │  unit  │ (matrix: ubuntu, macos)
         └────┬───┘
              │
       ┌──────┴──────┐
       ▼             ▼
┌──────────┐  ┌────────┐
│integration│  │ worker │
└─────┬─────┘  └────┬───┘
      └──────┬──────┘
             ▼
         ┌────────┐
         │coverage│
         └────────┘
```

`lint` and `typecheck` run in parallel — both must pass before `unit` starts. `integration` and `worker` run in parallel after `unit`. `coverage` aggregates after all three test jobs.

### Cost-aware sequencing

The graph is intentionally fail-fast on cheap failures:

- A ruff or format error fails CI in ~30 s without spinning up Python tests, browsers, or Redis.
- A mypy error fails in ~1 min without running tests.
- Unit tests fail before integration / worker tests start, so a regression in a fast unit test stops the more expensive jobs from launching.
- Coverage upload runs only after all tests succeed — no point uploading partial coverage on a failed run.

The `concurrency:` block at workflow level cancels in-progress runs when a newer commit pushes to the same ref. Saves CI minutes on rapid pushes.

### Markers as the test-sharding axis

Every test bears one of:

| Marker | Meaning | Default in CI? |
|---|---|---|
| (none) | unit test, no external deps | yes (`unit` job) |
| `slow` | takes >10 s | excluded by default; opt-in via `pytest -m slow` |
| `integration` | needs a real Chromium via Playwright | yes (`integration` job, ubuntu only) |
| `worker` | needs a Redis service running | yes (`worker` job, ubuntu only) |
| `llm` | makes Anthropic API calls (costs money) | **no** — gated to `llm-tests.yml` weekly + manual |

Adding a new category (e.g., `postgres` for tests against a real Postgres) = three steps:

1. Register the marker in `pyproject.toml` `[tool.pytest.ini_options].markers`.
2. Add a job to `ci.yml` with a `services: { postgres: ... }` block, calling `pytest -m "postgres and not llm"`.
3. Update each existing test job's `-m` filter to add `not postgres`.

The composite actions (`setup-environment`, `setup-browser`) are reused unchanged.

### Service containers and OS limits

GitHub Actions service containers (`services:`) only work on Linux runners. macOS and Windows runners can't run service containers. Implication:

- The `unit` matrix includes macOS to catch platform-specific issues, but only Ubuntu has `services: redis`. The `worker` job is Ubuntu-only.
- `integration` is Ubuntu-only too — Playwright is technically supported on macOS, but the marginal cost of running it cross-OS doesn't justify slow CI.
- Windows is documented as **not supported in v1** in `workflows/README.md`. The codebase aims at it (`.python-version 3.14`, ruff cross-platform) but no CI verifies it. Add later if there's demand.

### Caching strategy

| Cache | Key | Scope |
|---|---|---|
| uv | `uv.lock` hash | per-commit immutable |
| Playwright browsers | playwright version | invalidated on bump |
| mypy `.mypy_cache/` | source tree hash | per-job |
| pytest `.pytest_cache/` | source tree hash | per-job |
| ruff `.ruff_cache/` | source tree hash | per-job |

The composite `setup-environment` enables uv's built-in cache via `setup-uv@v3 enable-cache: true` — that handles the Python deps. Playwright caches itself under `~/.cache/ms-playwright/`; we don't manage it explicitly because the install step is idempotent and mostly cache-hit.

### Coverage aggregation

Each test job uploads `coverage.xml` as a named artifact (`coverage-unit-ubuntu-latest`, `coverage-integration`, `coverage-worker`). The `coverage` job downloads all of them and feeds the multi-file list to `codecov/codecov-action@v4`. Codecov merges client-side and posts the consolidated report.

If Codecov is unavailable (token missing on a fork), `fail_ci_if_error: false` keeps the build green and we lose only the upload — coverage XMLs are still attached as workflow artifacts for manual inspection.

### Triggers

- `push` to `main`: full pipeline.
- `pull_request` to `main`: full pipeline (matrix unit on both OSes).
- `workflow_dispatch`: manual trigger from the Actions tab.
- `schedule` for `llm-tests.yml`: Mondays 09:00 UTC. Skipped if `ANTHROPIC_API_KEY` secret is absent.

Dependabot opens PRs weekly for `github-actions` and `pip` ecosystems; CI runs against each PR like any other.

### Adding a new job (worked example: `db-postgres`)

To verify behavior against Postgres in addition to SQLite:

1. In `pyproject.toml` add the marker:
   ```toml
   markers = [
     ...,
     "postgres: marks tests that need a Postgres service",
   ]
   ```
2. In `ci.yml` add the job after `worker`:
   ```yaml
   db-postgres:
     needs: [unit]
     runs-on: ubuntu-latest
     services:
       postgres:
         image: postgres:16-alpine
         env:
           POSTGRES_PASSWORD: rpa
         ports: ["5432:5432"]
         options: --health-cmd pg_isready --health-interval 5s
     env:
       RPA_DATABASE_URL: postgresql+asyncpg://postgres:rpa@localhost:5432/postgres
     steps:
       - uses: actions/checkout@v4
       - uses: ./.github/actions/setup-environment
       - run: uv sync --extra postgres
       - run: uv run pytest -m "postgres and not llm" --cov --cov-report=xml
       - uses: actions/upload-artifact@v4
         with:
           name: coverage-postgres
           path: coverage.xml
   ```
3. Update `coverage` job's `needs:` and downloaded artifact list.
4. Add `not postgres` to existing test jobs' `-m` filters so Postgres-specific tests don't run twice.

Composite actions reused unchanged. The new job is roughly 25 lines.

## Concurrency

GitHub Actions concurrency / parallelism is the runtime story:

- **Workflow-level cancellation**: `concurrency.group: ci-${{ github.ref }}` + `cancel-in-progress: true` ensures a new push to the same branch cancels the prior run. Critical for fast PR iteration.
- **Job parallelism**: `lint` ‖ `typecheck`; `integration` ‖ `worker`. Limited by GitHub's per-account concurrent-job slots (free tier 20). On a busy fork, jobs queue.
- **Matrix parallelism**: `unit` runs ubuntu and macos in parallel.
- **`fail-fast: false`** on the matrix so a macOS-only flake doesn't kill the ubuntu run (you want both signals).
- **Service container readiness**: the `redis` service uses `--health-cmd "redis-cli ping"` so the worker job blocks until Redis is actually responding, not just started. Prevents flaky "connection refused" on first test.
- **No artifact races**: each job's coverage XML uses a unique artifact name; the aggregator job downloads with `pattern: coverage-*` so it picks up all of them deterministically.

## Medallion / worker integration

| Touch | Effect |
|---|---|
| Redis service | the `worker` job runs `redis:7-alpine` so M11.5's tests (`test_workers_jobs.py`, `test_e2e_medallion.py`) actually exercise Redis pub/sub, queue dynamics, and the Redis-backed locks |
| Bronze | tests use `tmp_path` for `bronze_root`; CI doesn't need a persistent bronze area. Each test gets a clean filesystem |
| Cold gold (DuckDB / pyarrow) | runs in-process within the `worker` job; no separate service. DuckDB on Linux is a wheel install via uv |
| Workers | the `worker` job spawns ARQ workers in-process for tests via the ARQ test runner — **no separate `arq` worker process** is needed in CI. M11.5's `test_workers_jobs.py` uses `arq.testing.Worker` to drive jobs synchronously |
| FastAPI | `test_api_e2e.py` (M12) is `@pytest.mark.integration` AND needs Redis, so it runs as part of the `worker` job (gets both browser via setup-browser and Redis via the service). Add `worker` marker to those E2E tests too if needed, or restructure markers to cover both — see *Pitfalls* |
| LLM | `llm-tests.yml` is its own workflow on a weekly schedule; the daily CI never spends LLM credits |

## Integration points

| Touch | File | How |
|---|---|---|
| M1 → M13 | [pyproject.toml](../pyproject.toml) | confirm pytest markers and dev-group dependencies |
| M5 → M13 | M5's storage layer is exercised in `unit` job (no DB external service needed — SQLite is in-process) |
| M6.5 → M13 | bronze writes covered in `unit` (with `tmp_path`) and `integration` (real Playwright) |
| M9 → M13 | LLM tests gated to `llm-tests.yml`; daily CI runs the mocked-SDK paths in `unit` |
| M11.5 → M13 | `worker` job's Redis service is the M11.5 `worker_queue` / `medallion_queue` testing surface |
| M12 → M13 | API E2E tests run inside the `worker` job (it has both browser and Redis); flagged as `integration and worker` |
| M14 → M13 | M14 docs reference CI badge: `![CI](https://github.com/<owner>/rpa-recorder/actions/workflows/ci.yml/badge.svg)` |

## Models / DB rows used

None — CI is meta-infrastructure. Tests use ephemeral SQLite (`tmp_path`) or seeded fixture DBs, plus the Redis service container for `worker` jobs. Postgres extra is uv-installed but only exercised by an opt-in job (worked example above).

## Tests

The CI workflow itself has no unit tests (YAML doesn't have a useful test layer at this scope). Validation strategy:

1. **Smoke validation** via `actionlint`: pre-commit hook runs `actionlint` against `.github/workflows/*.yml` to catch syntax / unused-step issues. Add `actionlint` to `.pre-commit-config.yaml`.
2. **Workflow run on a known-green commit** is the live test — push the M13 commit and watch all six jobs go green.
3. **Workflow run on a deliberately broken branch** verifies fail-fast: introduce a ruff error, push, observe `lint` fails in <1 min and downstream jobs are skipped.
4. **Local replication** via `act` (optional dev dependency): documented in `workflows/README.md` for contributors who want to debug CI locally before pushing.

If anyone changes `.github/`, the next CI run is the regression test. Worked changes go in their own commit titled `ci: <change>` for traceability.

## Known pitfalls

- **Service containers are Linux-only.** The `worker` job's `services: redis` block doesn't work on macOS or Windows runners. If we ever need cross-platform worker tests, the alternative is to spawn Redis as a step (e.g., `docker run -d redis`) — slower and noisier. Document the Linux-only constraint clearly.
- **Composite actions can't define `services:`.** That's why the Redis service is declared at the job level, not in `setup-environment`. Composite actions are limited to `steps:` only.
- **Playwright cache invalidation.** Playwright's browser binaries are pinned to the Playwright Python package version. When uv bumps Playwright, the cached browsers become stale. The `setup-browser` action runs `playwright install` unconditionally — fast on cache hit, slow (~30 s) on miss. Don't try to skip it.
- **`UV_CACHE_DIR` and macOS.** On macOS runners the default cache lives at a different path than Linux. `setup-uv@v3` handles this transparently; don't hardcode the path.
- **Codecov token on forks.** PRs from external forks don't get repo secrets, so `CODECOV_TOKEN` is empty. With `fail_ci_if_error: false` the upload silently no-ops; the rest of CI passes. Coverage XMLs still upload as workflow artifacts.
- **Concurrent-job slot limits.** GitHub Actions free tier allows ~20 concurrent jobs per account. A burst of PRs can queue jobs. Document expected wall-clock vs slot pressure in `workflows/README.md`.
- **`pytest -m` filter overlap.** With multiple markers (`integration`, `worker`, `llm`), the filter expressions get long. Use parentheses defensively: `-m "(worker or integration) and not llm"`. Test the filters locally before pushing.
- **Test markers on shared E2E tests.** `test_api_e2e.py` (M12) needs both browser AND Redis. Mark it `@pytest.mark.integration @pytest.mark.worker`. Then update the `integration` job's filter to exclude `worker` and the `worker` job's filter to include `worker` — the test runs once, in `worker`. Document this dual-marker pattern in `workflows/README.md`.
- **`actionlint` false positives.** Some valid uses (composite actions referencing local paths) trip its checks. Suppress targeted lines with `# actionlint:ignore` rather than disabling the linter wholesale.
- **`uv sync --frozen` requires `uv.lock` checked in.** Already true (M1). If anyone hand-edits `pyproject.toml` without running `uv lock`, CI fails with a helpful error.
- **`needs:` with skipped jobs.** If `worker` is skipped (e.g., feature flag in workflow), `coverage` waits forever unless we use `needs: [unit, integration, worker], if: always()`. Don't do that — better to keep all jobs always-running, gated by their own filters.
- **Dependabot churn.** Weekly PRs on `github-actions` and `pip` can add 5+ PRs/week. Keep `dependabot.yml` ecosystems tight (don't add npm if there's no JS); auto-merge minor bumps via a follow-up GitHub action if it becomes annoying.
- **Schedule drift on `llm-tests.yml`.** GitHub's cron has up to 15 min of jitter and can be skipped entirely on weekends if the platform is busy. For deterministic LLM testing, prefer `workflow_dispatch` after a meaningful change to prompts.
- **PEP 758 except syntax.** Python 3.14 allows parens-less `except A, B:`. CI runs ruff which is fine with both forms; just a heads-up if anyone wonders.

## Commit

`ci: add modular GitHub Actions workflows with composite actions and marker-based job sharding`

Body: implements the CI pipeline as six dependency-ordered jobs (lint, typecheck, unit, integration, worker, coverage) plus a separate weekly `llm-tests.yml`. Cheap jobs fail-fast (~30 s for ruff errors); expensive jobs (Playwright integration, Redis worker) only run if their prerequisites pass. Composite actions (`setup-environment`, `setup-browser`) keep job definitions DRY. Redis service container in the `worker` job exercises M11.5's queue / pub-sub / lock paths. Coverage XMLs from each test job aggregate into Codecov via the final `coverage` job. Adding a new test category (e.g., a `postgres` job) takes one marker registration + one job definition + a one-line filter update on existing jobs — composite actions reused unchanged. Includes `dependabot.yml` and `codecov.yml` for routine maintenance.

## Critical files

- `.github/workflows/ci.yml` — the primary pipeline
- `.github/workflows/llm-tests.yml` — gated weekly LLM tests
- `.github/actions/setup-environment/action.yml`, `setup-browser/action.yml` — composite reuse
- `.github/codecov.yml`, `.github/dependabot.yml` — routine config
- `pyproject.toml` — confirm `markers` list covers `slow`, `integration`, `llm`, `worker`
- `.pre-commit-config.yaml` — add `actionlint` hook (recommended)
