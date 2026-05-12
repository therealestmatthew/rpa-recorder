# Glossary

One-paragraph definitions of the domain terms used across the project.
Headings are stable so external links to specific terms don't break.
Cross-link to entries here from milestone docs and code comments rather
than re-defining inline.

## Action

A single browser interaction recorded or executed during a session — a
click, an input, a navigation, a key press. Carries an `ElementSelector`
identifying the target, a value when applicable, an `is_sensitive` flag,
and (after classification) a `SemanticIntent`. See
[`models/actions.py`](../src/rpa_recorder/models/actions.py).

## Backend (LLM)

A pluggable adapter to a specific model provider. The current backend is
`AnthropicBackend`. New backends implement the
`LLMBackend` Protocol in
[`classifier/llm/protocol.py`](../src/rpa_recorder/classifier/llm/protocol.py).

## Bronze

The raw tier of the medallion data layout. Append-only filesystem store
holding JSONL event streams, full-page screenshots, DOM dumps,
accessibility-tree snapshots, network HAR files, and per-LLM-call JSON
blobs. Operator-private (preserves `is_sensitive=True` payloads). See
[ADR-0001](../.claude/plans/adr/0001-medallion-bronze-silver-gold-split.md)
and [`medallion/README.md`](../src/rpa_recorder/medallion/README.md).

## Classification

The process of assigning a `SemanticIntent` to a `RecordedAction`. Runs
in two tiers: a heuristic pipeline first
([`classifier/heuristic/`](../src/rpa_recorder/classifier/heuristic/)),
then an LLM tier when heuristic confidence is below
`Config.classifier_confidence_threshold`.

## Cold gold

The Parquet-on-DuckDB half of the gold tier. Holds long-form analytical
data (replay scripts, training data) that benefits from columnar scans.
See [`medallion/gold_cold.py`](../src/rpa_recorder/medallion/gold_cold.py).

## ConfirmationRunner

The orchestrator for the M11 confirmation workflow. Drives a
filter→mode→renderer pipeline so an operator can review classifier
output before it lands as training data. See
[`confirmation/runner.py`](../src/rpa_recorder/confirmation/runner.py).

## ElementSelector

A small typed bundle identifying an element in the page: ordered list
of locators (data-testid, ARIA role+name, stable CSS, positional
XPath), plus stability hints. The executor walks them in priority order
during replay; recovery may rewrite them via `llm_reselect`.

## Filter

Two unrelated meanings — disambiguated by package:

- In [`classifier/heuristic/filters/`](../src/rpa_recorder/classifier/heuristic/filters/),
  a filter drops noise events from the action stream before
  classification (e.g., `drop_focus_blur_only`).
- In [`confirmation/filters/`](../src/rpa_recorder/confirmation/filters/),
  a filter narrows the candidate set to the actions an operator should
  review (e.g., `failed_on_replay`, `below_threshold`).

## Gold

The analytics tier of the medallion layout. Split into hot
(SQLite-backed dashboard aggregates) and cold (DuckDB-on-Parquet
training data and replay scripts).

## Heuristic engine

The pure-Python first tier of classification. Three-axis pipeline of
filters → normalizers → classifiers, each registered as a Protocol
implementation. See [`classifier/heuristic/engine.py`](../src/rpa_recorder/classifier/heuristic/engine.py).

## Hot gold

The SQLite half of the gold tier. Small, frequently-queried aggregates
that back the FastAPI dashboard endpoints. See
[`medallion/gold_hot.py`](../src/rpa_recorder/medallion/gold_hot.py).

## LLMBackend

A Protocol for the LLM tier — see *Backend (LLM)*.

## Mode (confirmation)

The orchestration shape of a confirmation pass: per-action,
per-intent-batch, diff-baseline, or overview. Modes drive the question
flow without owning rendering. See
[`confirmation/modes/`](../src/rpa_recorder/confirmation/modes/).

## Recording

A captured browser session: a `Recording` row plus its
`recorded_actions`, `network_events`, and bronze artifacts. Identified
by a stable `recording_id` (slug); the canonical row lives in the
`recordings` silver table.

## RecoveryAction

The output of a successful recovery strategy — a delta to the original
action's selector or behavior that lets replay continue. Persisted as
part of `execution_attempts`. See
[`recovery/protocol.py`](../src/rpa_recorder/recovery/protocol.py).

## Renderer (confirmation)

The visual shape of a confirmation question: compact, detailed, or
side-by-side. Renderers draw; modes orchestrate. See
[`confirmation/renderers/`](../src/rpa_recorder/confirmation/renderers/).

## Replay

Re-execution of a `Recording` against the live target. Each replay
produces a `RunResult` with per-action `ActionExecution` rows and
per-attempt `ExecutionAttempt` rows. Drives both the executor and the
recovery engine.

## RunResult

The top-level row for a single replay run — start time, end time,
status, and references to its `action_executions`. See
[`models/execution.py`](../src/rpa_recorder/models/execution.py).

## SemanticIntent

The classification output: `login`, `search`, `form_fill`,
`form_submit`, `navigation`, `confirmation`, `dismiss_modal`, plus a
confidence score. Lets downstream consumers (recovery, confirmation,
dashboards) reason about *what* the user was doing, not just *how*.

## Silver

The validated tier of the medallion layout. Typed Pydantic models
persisted via SQLAlchemy 2.0 across seven tables (`recordings`,
`recorded_actions`, `network_events`, `run_results`,
`action_executions`, `execution_attempts`, `llm_calls`) plus the
`bronze_artifacts` pointer index. The application reads from silver.

## Strategy (recovery)

A pluggable recovery tactic: `wait_and_retry`, `scroll_into_view`,
`dismiss_modal`, `frame_switch`, `llm_reselect`. Strategies run in
priority order; the first to succeed and pass verification wins. See
[`recovery/strategies/`](../src/rpa_recorder/recovery/strategies/).

## WorkerSettings

ARQ's per-worker configuration class. The project ships two —
`ReplayWorkerSettings` (queue: `replay_queue`, `max_jobs=2`) and
`MedallionWorkerSettings` (queue: `medallion_queue`, `max_jobs=10`,
plus cron jobs for compaction and retention). See
[`workers/README.md`](../src/rpa_recorder/workers/README.md).
