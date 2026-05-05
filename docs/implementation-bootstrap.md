# Implementation bootstrap — prompt for a new session

This file holds a single self-contained prompt you can paste into a fresh Claude Code session at `C:\build\rpa\`. The prompt drives the model through implementing M7 through M14 (plus the retrofit milestones M6.5 and M11.5), one at a time, against the detailed specs already committed under `docs/`.

The prompt does **not** re-design anything — every milestone has a finished spec; the new session's job is to **execute** against those specs.

## How to use

1. Open a new Claude Code session in `C:\build\rpa\` on the `dev` branch.
2. Paste the prompt below verbatim.
3. The agent will work through milestones one at a time, committing after each. It will pause at the spaced `/compact` checkpoints below.
4. After each milestone lands, review the diff. The milestone doc lists what to verify.

---

## The prompt

```
You are working in C:\build\rpa\ on the `dev` branch — a Python 3.14
browser-RPA portfolio project named `rpa_recorder`. M1–M6 are
implemented and committed (their historical-record docs live under
`docs/_archive/`). The remaining milestones — M7, M6.5, M8, M9, M10,
M11, M11.5, M12, M13, M14 — have detailed implementation specs in
`docs/`. Your job is to implement each one, in order, against its
spec.

## Orientation (Phase 1 — read these in order, fully, before touching code)

1. CLAUDE.md
2. docs/build-plan.md (especially §Concurrency conventions)
3. docs/medallion-and-workers.md (medallion + worker design depth)
4. docs/_archive/m1-project-scaffold.md through
   docs/_archive/m6-executor.md (what's already shipped)
5. The milestone doc you're about to work on
   (e.g. docs/m7-heuristic-classifier.md)

For each milestone, also peek at src/rpa_recorder/{models,storage,
browser}/ to ground the contracts your work plugs into.

## Implementation order

Work the milestones in this order. Each is independently shippable
and testable; do not skip ahead:

1. M7  — Heuristic classifier (modular pipelines).
        NOTE: a partial single-file implementation exists at
        src/rpa_recorder/classifier/heuristic.py (uncommitted). The
        M7 doc explicitly instructs you to delete that file and
        build the package layout instead.
2. M6.5 — Page scripts subdir + bronze layer (retrofit of M4
        recorder, M5 storage, M6 executor).
3. M8  — Modular Typer CLI package.
4. M9  — Pluggable LLM tier.
5. M10 — Modular recovery engine.
6. M11 — Modular confirmation workflow.
7. M11.5 — Workers + medallion promotion (ARQ + Redis).
8. M12 — Modular FastAPI control plane.
9. M13 — GitHub Actions CI.
10. M14 — Documentation polish (README, architecture.md,
        configuration.md, glossary.md, demo gif, LICENSE).

Why this order:
- M7 first to clear the in-progress uncommitted state.
- M6.5 next because its BronzeStore + BronzeWriter + bronze_artifacts
  table are foundational for M8 (record/replay routing artifacts via
  bronze), M9 (LLM call bronze writes), M10 (recovery bronze writes),
  M11.5 (silver promotion).
- M8–M11 are layered on M6.5 + M7.
- M11.5 consumes everything before it; M12 enqueues into M11.5.
- M13 needs the Redis service contract from M11.5 to test.
- M14 documents the finished system.

## Per-milestone workflow

For each milestone:

1. Read its docs/m*-*.md spec in full. Do not skim.
2. Read the integration-point docs called out in the spec.
3. Implement against the spec exactly:
   - Create every file listed under "Files / Create"
   - Modify every file listed under "Files / Modify"
   - Public API signatures match the spec verbatim
   - Behavior matches the bullet lists, including edge cases and
     known pitfalls
4. Add the prescribed tests under tests/. Hit the coverage target
   listed in the spec.
5. Run, in order:
   - uv sync
   - uv run ruff check .
   - uv run ruff format --check .
   - uv run mypy src/ tests/
   - uv run pytest -m "not llm and not integration"  (fast tier)
   - uv run pytest -m integration  (when Playwright is set up)
   - uv run pytest -m worker  (when Redis is up; M11.5+)
6. Commit with the exact message in the spec's "Commit" section.
   - Conventional Commits format (the spec already shows it).
   - NEVER include `Co-Authored-By: Claude` or any Claude
     attribution. This is an explicit repo norm enforced via the
     user's auto-memory.
7. Move on to the next milestone.

## Conventions (from build-plan.md and the milestone docs)

- Python 3.14; no `from __future__ import annotations`.
- Async everywhere; sync libs (DuckDB, pyarrow heavy ops) wrap in
  `asyncio.to_thread`.
- Type hints everywhere; mypy strict; ruff per pyproject.toml.
- Type-only imports under `if TYPE_CHECKING:`; runtime-evaluated base
  classes (Pydantic, pydantic-settings, SQLAlchemy ORM) are runtime
  imports per pyproject.toml's flake8-type-checking config.
- One AsyncEngine per process; AsyncSession per operation via
  get_session() context manager; never reused across operations.
- Browser per replay; BrowserSession is never shared across
  coroutines.
- Producer/consumer with bounded asyncio.Queue between high-rate
  sources and durable writers (recorder → bronze).
- asyncio.TaskGroup for fan-out; asyncio.Semaphore (per-instance,
  never module-global — they are event-loop-bound) for caps.
- ARQ job retry policy: idempotent jobs max_tries=3, non-idempotent
  (replay_run) max_tries=1.
- ARQ queue separation: replay_queue (max_jobs=2) and
  medallion_queue (max_jobs=10).
- SQLite WAL mode + busy_timeout=5000 in init_db(); document
  Postgres recommendation above ~2 concurrent workers.
- Anthropic SDK retries disabled (max_retries=0) so the project's
  RetryPolicy is the sole layer.
- Bronze writes are best-effort (logged, never raised — recording
  must never fail because bronze write failed).
- Conventional Commits (`feat(scope):`, `fix(scope):`,
  `docs(scope):`, `chore:`, `ci:`, `test(scope):`).
- No Co-Authored-By: Claude trailers anywhere.

## Pacing — when to /compact

Use /compact at the spaced checkpoints below to keep the prompt
cache hot. Do not compact more often than this — each compact
spends a cache miss.

- After M6.5 lands → /compact "M7 + M6.5 done; continue with M8"
- After M9 lands  → /compact "M8 + M9 done; continue with M10"
- After M11 lands → /compact "M10 + M11 done; continue with M11.5"
- After M11.5 lands → /compact "M11.5 done; continue with M12"
- After M13 lands → /compact "M12 + M13 done; continue with M14"

## What to do if you hit blockers

- Spec ambiguity or spec-vs-codebase contradiction: ask the user
  before deviating. The specs are detailed but not perfect.
- Test failure: fix the implementation, not the test, unless the
  test itself is wrong (rare). Tests are derived from the spec.
- Missing dependency: `uv add <pkg>`; commit the lock file change
  with `chore: add <pkg> dependency` in its own commit.
- Bug discovered in M1–M6 shipped code: flag it via
  mcp__ccd_session__spawn_task rather than fixing in the same
  commit as the milestone work.

## Stop conditions

- After each milestone, stop for user review unless explicitly told
  to continue. Each commit is a natural pause point.
- Stop immediately if you can't make progress for any reason — do
  not thrash. Ask for guidance.
- Stop after M14 lands.

## Verification at the end

After M14 commits, write a short report (≤200 words):
- Total commits made.
- Coverage achieved per package (cli/, classifier/, recovery/,
  confirmation/, workers/, medallion/, api/).
- Any flaky or skipped tests and why.
- Any deviations from the spec docs and why.

Then stop. Do not start a new milestone after M14.
```

---

## Notes for the human reading this

- The prompt embeds the `/compact` cadence at five points (after M6.5, M9, M11, M11.5, M13). Cache miss cost is amortized over ~2–3 milestones each, which is the cache window for a 1M-context Claude.
- The milestone order interleaves M6.5 between M7 and M8 because M7 has an existing partial implementation (clears in-progress state first) and M6.5's bronze layer is the foundational retrofit M8+ depends on.
- The agent is instructed to flag spec ambiguity rather than guess. The specs are detailed but cover hundreds of files / functions in aggregate; small gaps are inevitable.
- Expected implementation effort: ~10 milestones × 30–120 minutes each ≈ 6–18 hours of agent wall-clock, depending on test iteration and integration-test setup time (Playwright + Redis).
- The agent will end up with ~10 commits beyond the 11 already in the planning iteration. Final history will be ~21 commits on `dev` representing the full project arc.
- To run the implementation in a single uninterrupted batch, append "Do not stop between milestones; continue automatically" to the prompt's *Stop conditions* section. Default behavior is to pause for user review at each commit.
