# M14 — Documentation polish (audience-shaped, modular)

**Status:** pending

**Source:** [.claude/plans/bootstrap.md](../.claude/plans/bootstrap.md) §README Requirements; [build-plan.md](build-plan.md) for cross-linking conventions; [medallion-and-workers.md](medallion-and-workers.md) for the architecture diagram.

## Goal

Make the project portfolio-ready by shipping a documentation set structured around three audiences: the *evaluator* who decides in 60 seconds whether to keep reading (README), the *contributor* who needs the dev loop and architecture walk-through (CONTRIBUTING.md + architecture.md), and the *integrator* who wants the configuration surface and conceptual model (configuration.md + glossary.md). Each doc is short and self-contained; new concepts drop in as new files cross-linked from the README and architecture entry points.

The architecture doc is itself modular — one section per layer (capture, bronze, silver, gold, classifier, recovery, confirmation, workers, API) so adding a new layer = a new section + entries in the cross-link tables. No prose rewrites of the existing layers.

## Files

### Create

- `README.md` — primary entry point (≤200 lines)
- `LICENSE` — MIT, attribute Matthew Mulé
- `CHANGELOG.md` — [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format, version 0.1.0 entry
- `CONTRIBUTING.md` — dev loop, commit conventions (no Claude attribution per repo norm), PR checklist
- `SECURITY.md` — how to report vulnerabilities; references `is_sensitive` redaction guarantees
- `docs/architecture.md` — layered walkthrough (capture → bronze → silver → gold → workers → API)
- `docs/configuration.md` — exhaustive `RPA_*` env var reference table
- `docs/glossary.md` — one-paragraph definitions of Recording, Action, SemanticIntent, RunResult, RecoveryAction, Bronze/Silver/Gold, etc.
- `docs/demo.gif` — recorded session (≤30 s, ≤5 MB)

### Modify

- `docs/build-plan.md` — already exists from earlier in this iteration; add a final "Status: complete" line under M14 once shipped
- `pyproject.toml` — confirm `readme = "README.md"` entry resolves; add `[project.urls]` for Homepage / Repository / Issues / Documentation

### Optional (CI/doc-quality)

- `.markdownlint.yaml` — markdown style config
- `.github/workflows/docs.yml` — separate workflow that runs markdownlint + lychee link checker on every push (or fold into M13's `lint` job)

## README structure (≤200 lines, audience: 60-second evaluator)

Sections in order:

1. **Title + tagline.** "rpa-recorder — semantic browser RPA with LLM-powered recovery."
2. **Demo GIF.** `![demo](docs/demo.gif)` — single inline image, no caption needed.
3. **Status badges.** CI badge, Codecov badge, Python version badge, license badge, lint/format badges. Automated by M13's CI.
4. **What it does** (≤3 sentences). Records browser actions with semantic context, classifies them by intent, replays with multi-strategy resilience, recovers via LLM when selectors drift.
5. **Why it's different** (≤4 bullets). Semantic replay; LLM-powered recovery; medallion data lake (bronze→silver→gold) for analytics + training data; ARQ workers so replays scale.
6. **Architecture preview** (mermaid block, 8 nodes max). High-level: Browser → Recorder → Bronze → Silver → Gold; ARQ workers as a side block; FastAPI as the entry point. Link "→ See [docs/architecture.md](docs/architecture.md) for the full walk-through."
7. **Quickstart** (copy-pasteable PowerShell + bash variants).
   ```powershell
   uv sync
   uv run playwright install chromium
   docker compose up -d redis
   uv run rpa worker --workers 2
   uv run rpa record demo --url https://example.com
   uv run rpa replay demo
   ```
8. **Concepts.** Four short paragraphs (Recording, Action, SemanticIntent, RunResult). Link to [docs/glossary.md](docs/glossary.md) for the rest.
9. **Configuration.** Three-line summary + link to [docs/configuration.md](docs/configuration.md). Don't inline the table — keep the README under 200 lines.
10. **Roadmap.** Checklist of M1–M14 + future ideas. Pulled from [docs/build-plan.md](docs/build-plan.md).
11. **Contributing.** One paragraph + link to [CONTRIBUTING.md](CONTRIBUTING.md).
12. **License.** MIT.

The README is intentionally a navigation hub. New concepts that warrant their own page get a one-line entry in *Concepts* with a link out — they don't dilute the 60-second pitch.

## architecture.md structure (≤500 lines, audience: contributor walking the codebase)

One section per architectural layer. Each section follows the same shape so a new layer drops in by adding a section:

```
## <Layer name>

**Purpose** (one sentence)

**Key files** (links with line refs)

**Depends on** (which earlier layers it uses)

**Extension points** (where contributors plug in new behavior)

**See also** (link to milestone doc)
```

Sections, in order matching the data flow:

1. **Capture (page-side JS)** — `page_scripts/recorder/inject.js`; depends on Playwright; extension via `page_scripts/{recorder,replay,shared}/`; → [m6.5](m6.5-page-scripts-and-bronze.md).
2. **Bronze (raw artifacts)** — `BronzeStore`, `LocalFilesystemStore`, `bronze_artifacts` table; depends on filesystem + DB; extension via implementing `BronzeStore` Protocol (S3 / MinIO future); → [m6.5](m6.5-page-scripts-and-bronze.md).
3. **Silver (validated rows)** — the seven SQLAlchemy tables; depends on bronze for promotion source; extension via new `*Repository` classes; → [_archive/m5](_archive/m5-storage-layer.md).
4. **Gold (analytics)** — hot SQLite tables + cold DuckDB-on-Parquet; depends on silver; extension via new gold tables in `medallion/gold_hot.py` or `gold_cold.py`; → [m11.5](m11.5-workers-and-medallion-promotion.md).
5. **Heuristic classifier** — `classifier/heuristic/` three-pipeline architecture; depends on M2 models; extension via new rule modules in `filters/`, `normalizers/`, `classifiers/`; → [m7](m7-heuristic-classifier.md).
6. **LLM classifier** — `classifier/llm/` pluggable backends/prompts/parsers; depends on heuristic; extension via new backend / prompt / merge strategy; → [m9](m9-llm-classifier.md).
7. **Recovery** — `recovery/strategies/` modular pipeline with verifier; depends on LLM classifier (for `LLMReselect`); extension via new strategy module; → [m10](m10-recovery-engine.md).
8. **Confirmation** — `confirmation/` filter/mode/renderer pipeline; depends on M5 + M9; extension via new filter / mode / renderer; → [m11](m11-confirmation-workflow.md).
9. **Workers (ARQ + Redis)** — `workers/` package with seven jobs; depends on bronze + silver + gold; extension via new job module + registry entry; → [m11.5](m11.5-workers-and-medallion-promotion.md).
10. **CLI (Typer)** — `cli/commands/` per-command modules; depends on every operational layer; extension via new command file; → [m8](m8-cli-commands.md).
11. **API (FastAPI)** — `api/routers/` per-resource routers + middleware stack + WebSocket manager; depends on workers (enqueue) + Redis (pub/sub) + DB (reads); extension via new router; → [m12](m12-fastapi-control-plane.md).

Cross-cutting sections after the layered walk:

- **Concurrency model** — pulls from [build-plan.md §Concurrency conventions](build-plan.md#concurrency-conventions). One paragraph each on async-everywhere, engine pooling, browser-per-replay, bounded queues, semaphores, structured concurrency, Redis locks. Reader can scan in 2 minutes.
- **Data flow diagram** — single mermaid block showing how a recording becomes a replay-ready training example: Browser event → JSONL bronze → Pydantic-validated silver → gold dashboard / training Parquet. Annotated with which milestone owns each arrow.
- **Adding a new layer** (worked example) — walks through what a hypothetical "Visual diff layer" would touch (page_scripts, bronze, silver schema, M11.5 promotion, gold table, README mention). Demonstrates that the seams are explicit, not hidden.

## configuration.md structure (single table, audience: integrator)

Exhaustive table of every `RPA_*` env var (and corresponding `Config` field), one row each:

| Var | Type | Default | Description | Source milestone |
|---|---|---|---|---|
| `RPA_DATABASE_URL` | str | `sqlite+aiosqlite:///rpa.db` | SQLAlchemy connection URL | M5 |
| `RPA_REDIS_URL` | str | `redis://localhost:6379/0` | Redis for ARQ + pub/sub + cache | M11.5 |
| `RPA_BRONZE_ROOT` | path | `./data/bronze` | bronze layer root | M6.5 |
| `RPA_GOLD_COLD_ROOT` | path | `./data/gold/cold` | DuckDB Parquet root | M11.5 |
| `RPA_BRONZE_RETENTION_JSONL_DAYS` | int | `30` | hot JSONL retention | M6.5 |
| `RPA_BRONZE_QUEUE_SIZE` | int | `1000` | recorder→bronze queue cap | M6.5 |
| `RPA_WORKER_CONCURRENCY` | int | `2` | default `max_jobs` per ARQ worker | M11.5 |
| `RPA_MAX_QUEUE_DEPTH` | int | `100` | FastAPI 429 threshold | M12 |
| `RPA_LLM_MAX_CONCURRENCY` | int | `5` | per-LLMClassifier semaphore | M9 |
| `RPA_LLM_DAILY_BUDGET_USD` | float | `5.0` | per-day cap; raises `LLMBudgetExceeded` | M9 |
| `RPA_CLASSIFIER_CONFIDENCE_THRESHOLD` | float | `0.7` | hybrid threshold for LLM escalation | M9 |
| `RPA_RECOVERY_MAX_DEPTH` | int | `1` | suppresses recursive recovery | M10 |
| `RPA_RATE_LIMIT_PER_MINUTE` | int | `60` | per-IP rate limit | M12 |
| `RPA_WS_HEARTBEAT_S` | float | `30.0` | WebSocket keep-alive interval | M12 |
| `ANTHROPIC_API_KEY` | secret | required for LLM tier | not prefixed (Anthropic SDK reads it directly) | M9 |
| `CODECOV_TOKEN` | secret | optional | CI coverage upload | M13 |

Each row links to the milestone doc that introduced or owns the field. New `Config` fields auto-add a row here at milestone time — enforced by a CONTRIBUTING.md checklist item.

## glossary.md structure (one paragraph per term)

Lifted from [.claude/plans/bootstrap.md](../.claude/plans/bootstrap.md) §Concepts and extended with medallion-era terms. Stable headings so external links don't break. Terms (alphabetical): `Action`, `Bronze`, `Classification`, `Cold gold`, `ConfirmationRunner`, `ElementSelector`, `Filter` (recovery / confirmation overload — disambiguate), `Gold`, `Heuristic engine`, `Hot gold`, `LLMBackend`, `Recording`, `RecoveryAction`, `Replay`, `RunResult`, `SemanticIntent`, `Silver`, `Strategy` (recovery), `WorkerSettings`.

The glossary is the cross-cutting index — every milestone doc that introduces a term should link to its glossary entry rather than re-defining inline.

## CONTRIBUTING.md structure (audience: contributor)

Sections:

1. **Dev loop** — `uv sync` → `uv run rpa --help` → `uv run pytest` → `uv run ruff check .` → commit.
2. **Branching** — feature branches off `main`; rebase before PR.
3. **Commit conventions** — Conventional Commits (`feat(scope):`, `fix(scope):`, `docs(scope):`, `chore:`); subject ≤72 chars; body explains *why*; **never include Claude attribution / Co-Authored-By: Claude trailers** (this repo's explicit norm — gets enforced via the user's auto-memory).
4. **PR checklist** — tests added, lint/type/test green locally, milestone doc updated if scope changed, configuration.md row added if new env var.
5. **Local dev with Redis** — `docker compose up -d redis` instructions.
6. **Running LLM tests locally** — set `ANTHROPIC_API_KEY`, `RPA_RUN_LLM_TESTS=1`, run `uv run pytest -m llm`.
7. **Adding a milestone** — link to [build-plan.md §Conventions for milestone docs](build-plan.md#conventions-for-milestone-docs).

## SECURITY.md structure (audience: security-conscious user)

Brief — half a page. Covers:

1. **Reporting** — email address; preferred 90-day disclosure window.
2. **Trust boundaries** — `is_sensitive=True` payloads are redacted from LLM prompts (M9 invariant), API responses (M12 redact context), and CLI rendering (M8 detail renderer). Bronze JSONL preserves raw values — bronze is private to the operator.
3. **Secret handling** — `ANTHROPIC_API_KEY` via `pydantic.SecretStr`; never logged; never committed.
4. **Threat model exclusions** — multi-tenant isolation is out of scope (single-operator portfolio tool); replay against authenticated targets requires manual `storage_state` (M3); no defenses against malicious recorded sites (the operator owns trust).

## CHANGELOG.md initial entry

```markdown
# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - YYYY-MM-DD

### Added
- M1 project scaffold (uv, pyproject, ruff, mypy, pytest).
- M2 Pydantic data models (RecordedAction, Recording, RunResult, LLMCall, ...).
- M3 BrowserSession async context manager.
- M4 Recorder with page-side JS capture.
- M5 Async SQLAlchemy 2.0 storage with seven silver tables.
- M6 Executor with multi-strategy selector resolution.
- M6.5 Page scripts subdir split + bronze layer (BronzeStore, BronzeWriter, bronze_artifacts table, producer/consumer queue).
- M7 Modular heuristic classifier (filter / normalize / classify pipelines).
- M8 Modular Typer CLI package (`record`, `list`, `show`, `classify`, `replay`, `serve`).
- M9 Pluggable LLM tier (backends, prompts, parsers, retry, cache, merge, budget guard).
- M10 Modular recovery engine (wait_and_retry, scroll_into_view, dismiss_modal, frame_switch, llm_reselect).
- M11 Modular confirmation workflow (filter / mode / renderer pipeline).
- M11.5 ARQ + Redis workers, silver and gold promotion (hot SQLite + cold DuckDB-on-Parquet).
- M12 Modular FastAPI control plane (per-resource routers, middleware stack, WebSocket manager).
- M13 GitHub Actions CI with composite actions and marker-based job sharding.
- M14 Documentation set (README, architecture, configuration, glossary, demo gif, LICENSE).
```

## demo.gif production

Recorded locally — not generated by code:

1. `uv run rpa record demo --url https://example.com --headless=false` against a representative target (a public form-fill site is good — no credentials).
2. Replay it: `uv run rpa replay demo`.
3. Capture with a screen recorder of choice (LICEcap on macOS / ScreenToGif on Windows).
4. Trim to ≤30 s, ≤5 MB; save as `docs/demo.gif`.
5. Verify rendering at GitHub's display size (preview the README on the branch before merging M14).

GIF stays out of git LFS for now (5 MB is fine in plain git). If multiple GIFs accumulate, switch to LFS.

## Cross-link integrity

A documented invariant: every link from one doc to another uses the relative path (e.g., `docs/architecture.md` from README, `architecture.md` from glossary). Absolute paths or external URLs to the repo are forbidden in committed docs (they break on forks). Enforced via:

- A pre-commit hook running `lychee --offline docs/ README.md CHANGELOG.md CONTRIBUTING.md SECURITY.md` to catch broken intra-repo links.
- Optional: `.github/workflows/docs.yml` runs the same check in CI on every push, so external link rot is also caught (lychee can be online-mode in CI).

## Adding a new doc (worked example: `docs/operations.md`)

If we ever want a runbook for production operators:

1. Create `docs/operations.md` with sections for daily checks, incident response, scaling guidance.
2. Add a one-liner under README's *Concepts* (or a new *Operations* section) linking to it.
3. Add a glossary entry if it introduces new terms.
4. Add a row to `docs/configuration.md` if it documents new env vars.
5. Pre-commit lychee verifies the new links resolve.

No edits to architecture.md, milestone docs, or other concept docs.

## Concurrency / worker integration

N/A at the doc layer itself, but the docs *describe* the concurrency model in two places:

- **README architecture preview** — one mermaid block + a sentence on workers.
- **architecture.md §Concurrency model** — pulls the canonical [build-plan.md §Concurrency conventions](build-plan.md#concurrency-conventions) table verbatim with one-paragraph commentary on each row. Don't fork the rules across two docs — keep build-plan as the source of truth and architecture.md as the narrative.

## Integration points

| Touch | File | How |
|---|---|---|
| All milestones → M14 | every `m*.md` | architecture.md links to each via the per-layer "See also" line |
| M5 / M9 / M11.5 / M12 → M14 | `Config` fields | every new `RPA_*` env var must add a row to configuration.md (CONTRIBUTING.md checklist enforces) |
| M11.5 → M14 | medallion data layout | README's *Why it's different* mentions bronze→silver→gold; architecture.md §Bronze/§Silver/§Gold sections cover details |
| M13 → M14 | CI badges | README badge URLs reference M13's workflow names |

## Models / DB rows used

None — docs don't read DB. configuration.md describes Pydantic `Config` fields by reading the source-of-truth file; that's a manual sync, not a runtime dependency.

## Tests

Documentation has three quality gates rather than unit tests:

1. **Markdown lint** — `markdownlint` (or `markdownlint-cli2`) in pre-commit + CI. Catches inconsistent headings, broken tables, missing alt text on images.
2. **Link checker** — `lychee --offline docs/ *.md` in pre-commit catches intra-repo link breaks. CI runs full online mode weekly to catch external link rot.
3. **Build smoke** — `mkdocs build --strict` (if adopted) or simply `git diff --check` for whitespace issues. Optional.

No traditional pytest tests for docs. The validation is "does the next contributor following the README get to a working `rpa replay demo`?" — measured by trial, not assertion.

## Known pitfalls

- **README length creep.** Every new milestone wants to mention its feature in the README. Resist — link out instead. Hard cap: 200 lines. CONTRIBUTING.md adds a PR checklist item: "If you added a new feature, add a glossary entry and update build-plan.md, *not* the README, unless the feature changes the elevator pitch."
- **GIF size and quality trade-off.** 30 s at decent resolution can hit 10 MB easily. Lower the FPS to 8–10 (it's a UI demo, not animation) and use a 600 px-wide capture. If still too large, swap to a hosted MP4 + a static screenshot fallback in the README.
- **Mermaid rendering varies.** GitHub renders mermaid in markdown reliably; some other viewers (older GitLab, some IDEs) don't. Provide image fallbacks for any diagram in architecture.md that's mission-critical.
- **External link rot.** Bootstrap spec, Anthropic docs, Playwright docs all change URLs over years. Run lychee in online mode periodically (weekly CI) and update.
- **Configuration table drift.** A `Config` field added to `config.py` without a row in configuration.md is a footgun — silent feature divergence. Enforce via CONTRIBUTING.md PR checklist + a future test that imports `Config` and diffs field names against the markdown table headers.
- **Glossary overload.** Tempting to define everything; resist. Glossary is for terms that appear in *multiple* docs. Single-doc terms get an inline definition where they appear.
- **License header expectations.** MIT does not require per-file headers, and the source files don't currently have them. Don't add them — clutter without legal benefit.
- **Demo GIF privacy.** Screenshots can leak environment data (browser tabs, system fonts revealing OS). Record in a clean profile (incognito Chrome, fresh window position). Crop to the relevant pane.
- **CHANGELOG drift.** Manual maintenance — easy to forget. Add a CONTRIBUTING.md PR checklist item; consider [release-please](https://github.com/googleapis/release-please) later if it becomes a pain.
- **Roadmap section in README.** Goes stale fast. Either auto-derive from build-plan.md (single source of truth) or remove the section entirely and link to build-plan.md instead. Recommend the latter — fewer manual sync points.
- **PEP 758 except syntax.** Worth noting in CONTRIBUTING.md so contributors don't "fix" the existing parens-less form thinking it's a bug.

## Commit

`docs: add README, architecture, configuration, glossary, contributing, security, changelog, demo gif, and license`

Body: ships the documentation set as audience-shaped, modular files. README is a 60-second navigation hub (≤200 lines) linking out to deeper docs rather than inlining details. architecture.md walks the codebase by layer with a uniform per-section shape (purpose / key files / depends-on / extension points / see-also link to milestone doc) so adding a new layer = adding a new section. configuration.md is the single env-var reference; CONTRIBUTING.md PR checklist enforces it stays in sync. glossary.md cross-links every domain term in one place. CHANGELOG.md follows Keep a Changelog. Demo gif ≤30 s recorded locally against a public site (no credentials). lychee in pre-commit catches broken intra-repo links; weekly CI catches external rot.

## Critical files

- `README.md` — primary entry point
- `LICENSE` — MIT
- `docs/architecture.md` — layered walk-through
- `docs/configuration.md` — env var reference
- `docs/glossary.md` — cross-cutting term definitions
- `docs/demo.gif` — recorded session
- `CHANGELOG.md`, `CONTRIBUTING.md`, `SECURITY.md` — repo-root maintenance docs
- `.markdownlint.yaml` — style config (optional but recommended)
- Pre-commit hooks for `markdownlint` + `lychee` (optional but recommended)
