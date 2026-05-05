# Enhance milestone plans — prompt for a new session

This file holds a single self-contained prompt you can paste into a fresh Claude Code session at `C:\build\rpa\`. The prompt drives the model through `docs/m7-*.md` … `docs/m14-*.md`, enhancing each one in place so the resulting plans are **detailed enough to execute without re-reading the bootstrap spec each time**.

The prompt does **not** implement any milestone — it only updates the planning markdown. M1–M6 docs are the implemented record and must not be edited.

## How to use

1. Open a new Claude Code session in `C:\build\rpa\` on the `dev` branch.
2. Paste the prompt below verbatim.
3. Let the agent run. It will pause for `/compact` at the spaced checkpoints.
4. After the agent finishes M14, review the diffs with `git diff docs/`.

---

## The prompt

```
You are working in C:\build\rpa\ on the `dev` branch — a greenfield Python
3.14 browser-RPA portfolio project named `rpa_recorder`. M1–M6 are
implemented and committed. M7 is partially implemented (a heuristic
classifier file exists at src/rpa_recorder/classifier/heuristic.py but
is uncommitted — IGNORE that file for the purposes of this task; you are
not implementing or committing anything).

## Goal

Enhance the plan markdown for milestones M7 through M14 in `docs/`.
Each plan currently captures the high-level shape but is too thin to
execute from. Bring each up to the level of detail that the M1–M6 docs
demonstrate (look there for the standard).

## What to read first (Phase 1 — orientation)

Read in this exact order, fully:

1. CLAUDE.md
2. .claude/plans/bootstrap.md   (~784 lines — the canonical spec)
3. .claude/plans/data-capture.md (~150 lines — the JSON/data shape spec)
4. docs/m1-project-scaffold.md
5. docs/m2-data-models.md
6. docs/m3-browser-session.md
7. docs/m4-recorder.md
8. docs/m5-storage-layer.md
9. docs/m6-executor.md

Then skim m7 through m14 to see their current state. Also peek at
src/rpa_recorder/models/ and src/rpa_recorder/storage/ to ground the
contracts that later milestones build on. DO NOT read implementation
files other than the models, storage layer, and the existing executor
hook — those are the integration surfaces M7+ touch. There's no need to
re-read every line of every implementation file.

## What "enhanced" means

For each of m7-*.md … m14-*.md, the final document must include:

- **Goal** (one paragraph, why this milestone exists in the build order).
- **Files** — exact paths to create or modify, including test files.
- **Public API** — full signatures for every new class/function, with
  type annotations matching the project's strict mypy + ruff settings
  (Python 3.14, `from __future__ import annotations` is NOT used in this
  project; runtime-needed types are runtime-imported, type-only imports
  go under `if TYPE_CHECKING:`).
- **Behavior** — bullet-by-bullet of what each function does, including
  edge cases, raised exceptions, and any tricky ordering / async
  concurrency notes.
- **Integration points** — where this milestone plugs into earlier
  milestones, with file/line-ish references (e.g. "Executor.
  _attempt_recovery in src/rpa_recorder/browser/executor.py replaces
  the stub returned None").
- **Models / DB rows used** — explicit list of which Pydantic models
  and SQLAlchemy rows from M2/M5 the milestone reads or writes.
- **Tests** — concrete `tests/test_*.py` filename, list of test
  function names, what each asserts, and what fixtures are needed
  (mocks, tmp_path, real Chromium via @pytest.mark.integration, etc.).
  Aim for the same level of specificity as docs/m6-executor.md's tests
  section.
- **Known pitfalls** — anything you'd have to discover by trial and
  error otherwise. Examples: ruff TC002 vs Playwright introspection,
  Python 3.14 PEP 758 stripping `except (...)` parens, asyncio
  serialization of capture handlers. Carry these forward where they
  apply.
- **Commit message** — already present in each doc; keep it but
  refine the body if the scope crystallized.

Cross-reference the bootstrap spec section by section. Where the
bootstrap spec contradicts what's in the M5 implementation (e.g., the
spec lists 6 storage tables but M5 ships 7 including llm_calls),
trust the M5 doc and update the milestone plan to match.

## Workflow & pacing

Do the milestones in numeric order. After each milestone is updated,
state in 1 sentence what changed. Use Edit (not Write) for these files
so the diff is reviewable.

Run `/compact` at the spaced checkpoints below to keep cache hot
and the working set tight:

  - After M8 is updated  → /compact "M7-M8 enhanced; continue with
    M9-M11"
  - After M11 is updated → /compact "M9-M11 enhanced; continue with
    M12-M14"

Don't /compact more often than that — each compact spends a cache
miss, and the 1M context handles 3–4 milestones comfortably.

## What not to do

- DO NOT modify docs/m1-*.md … docs/m6-*.md (those are the historical
  record).
- DO NOT modify .claude/plans/bootstrap.md, .claude/plans/data-
  capture.md, or any source code under src/.
- DO NOT run pytest, ruff, mypy, or git commands. This is a docs-only
  task.
- DO NOT create new files in docs/ other than incidental notes if you
  must (and only after asking).
- DO NOT delete the existing content of m7-*.md … m14-*.md; preserve
  their structure and add to it.
- DO NOT add Co-Authored-By: Claude trailers anywhere (irrelevant
  here since you won't be committing, but stated for safety).

## Verification

When done, write a short final report (≤200 words) summarizing:
- Lines added per milestone doc.
- Any contradictions you found between bootstrap.md and the implemented
  M1–M6 reality, and how you resolved them in the plan.
- Any milestones whose plan you think still needs more thought before
  implementation can start.

Stop after the report. Do not ExitPlanMode, do not make commits, do not
ask "should I proceed?" — your job ends with the report.
```

---

## Notes for the human reading this

- The prompt embeds the cache-aware `/compact` cadence (after M8 and after M11) so the agent doesn't burn cache misses by compacting too often, and doesn't run out of headroom by never compacting.
- The "ignore the uncommitted heuristic.py" hint prevents the new session from getting confused that M7 is partially built.
- The prompt tells the agent to look at M1–M6 docs as the *standard* — they are what an "enhanced" plan should look like.
- Total expected runtime is roughly 8 milestone × 2–4 minutes + 2 compact pauses ≈ 25–40 minutes wall-clock on a typical session.
