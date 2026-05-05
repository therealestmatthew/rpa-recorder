# M11 — Confirmation workflow (modular review pipeline)

**Status:** pending

**Source:** [.claude/plans/bootstrap.md](../.claude/plans/bootstrap.md) §CLI Specification (`rpa confirm`); [build-plan.md](build-plan.md) §Concurrency conventions; [m8-cli-commands.md](m8-cli-commands.md) for the per-command-module shape this plugs into. Replaces the original sketch with a three-axis plugin layout (filters, review modes, renderers) so new review flows drop in without rewriting the loop.

## Goal

An interactive `rpa confirm <id>` CLI command that walks low-confidence (or otherwise interesting) classified actions and lets the user accept the classifier's label, relabel it, or skip. The command is structured around three pluggable concerns:

1. **Filter** — selects which actions need review (default: confidence below threshold). Other filters: by intent, failed-on-replay-only, unconfirmed-only, since-date.
2. **Review mode** — orchestrates the interactive loop (default: per-action sequential). Other modes: per-intent batch (review all SEARCH actions at once), overview (auto-accept high-confidence, only review the rest), diff-against-baseline (review only what changed since last classification).
3. **Renderer** — formats action context for the user (default: compact table). Other renderers: detailed (full element_context + screenshot path), side-by-side (heuristic vs LLM verdict).

Persistence is the M5 `RecordingRepository`. After the pass completes, the runner enqueues `promote_silver_to_gold(recording_id=...)` (M11.5) so the dashboard reflects the new labels and `gold_training_data.parquet` picks up the confirmed examples for downstream use.

The architecture means: adding "bulk-confirm all SEARCH actions in this recording" = a new `PerIntentBatchMode` module + registry entry + unit test. No edits to the runner, the renderer, or any existing mode.

## Files

### Create

- `src/rpa_recorder/cli/commands/confirm.py` — Typer command per the M8 per-command-module shape; thin wrapper that builds a `ConfirmationRunner` and invokes it
- `src/rpa_recorder/confirmation/__init__.py` — public API: `ConfirmationRunner`, `default_runner`, `Filter`, `ReviewMode`, `Renderer`, `Decision`, `ReviewSummary`
- `src/rpa_recorder/confirmation/protocol.py` — Protocols + Pydantic models
- `src/rpa_recorder/confirmation/runner.py` — `ConfirmationRunner` orchestrator
- `src/rpa_recorder/confirmation/filters/__init__.py` — explicit registry: `default_filters()`
- `src/rpa_recorder/confirmation/filters/below_threshold.py`
- `src/rpa_recorder/confirmation/filters/by_intent.py`
- `src/rpa_recorder/confirmation/filters/failed_on_replay.py`
- `src/rpa_recorder/confirmation/filters/unconfirmed_only.py`
- `src/rpa_recorder/confirmation/filters/since_date.py`
- `src/rpa_recorder/confirmation/modes/__init__.py` — `default_modes()`
- `src/rpa_recorder/confirmation/modes/per_action.py` — sequential review (default)
- `src/rpa_recorder/confirmation/modes/per_intent_batch.py` — bulk review by intent group
- `src/rpa_recorder/confirmation/modes/overview.py` — summary table + targeted dives
- `src/rpa_recorder/confirmation/modes/diff_baseline.py` — review only what changed
- `src/rpa_recorder/confirmation/renderers/__init__.py` — `default_renderers()`
- `src/rpa_recorder/confirmation/renderers/compact.py` — one row per action
- `src/rpa_recorder/confirmation/renderers/detailed.py` — full element_context, payload (redacted), failure history if any
- `src/rpa_recorder/confirmation/renderers/side_by_side.py` — heuristic + LLM verdict columns (M9 source attribution)
- `tests/test_confirmation_protocol.py`
- `tests/test_confirmation_filters.py`
- `tests/test_confirmation_renderers.py`
- `tests/test_confirmation_modes.py`
- `tests/test_confirmation_runner.py`
- `tests/test_cli_confirm.py` — `CliRunner`-driven end-to-end with scripted stdin

### Modify

- `src/rpa_recorder/cli/commands/__init__.py` — add `from . import confirm` to register the command (M8's registration site)
- `src/rpa_recorder/storage/repositories.py` — add `RecordingRepository.update_action_classification(action_id, *, intent, user_confirmed, user_label)` for per-action partial updates (M5 currently only has full-recording save)
- `src/rpa_recorder/config.py` — add `confirmation_default_filter: str = "below_threshold"`, `confirmation_default_mode: str = "per_action"`, `confirmation_default_renderer: str = "compact"`

## Public API

### `confirmation/protocol.py`

```python
class Decision(str, Enum):
    ACCEPT = "accept"
    RELABEL = "relabel"
    SKIP = "skip"


class ActionReviewResult(BaseModel):
    action_id: UUID
    decision: Decision
    new_label: SemanticIntent | None = None       # set when decision == RELABEL
    reviewed_at: datetime


class ReviewSummary(BaseModel):
    recording_id: UUID
    total_candidates: int                          # actions the filter selected
    accepted: int
    relabeled: int
    skipped: int
    duration_s: float
    results: list[ActionReviewResult]


class Filter(Protocol):
    name: str

    def select(
        self, recording: Recording, *, threshold: float
    ) -> list[RecordedAction]:
        """Return the subset of actions that need review."""


class Renderer(Protocol):
    name: str

    def render_action(
        self, action: RecordedAction, *, context: dict[str, Any] | None = None
    ) -> RenderableType:
        """Build a Rich renderable describing one action."""

    def render_summary(self, summary: ReviewSummary) -> RenderableType: ...

    def render_intent_batch(
        self, intent: SemanticIntent, actions: list[RecordedAction]
    ) -> RenderableType:
        """Used by PerIntentBatchMode. Default impl can render_action each."""


class ReviewMode(Protocol):
    name: str

    async def review(
        self,
        candidates: list[RecordedAction],
        *,
        renderer: Renderer,
        on_decision: Callable[[ActionReviewResult], Awaitable[None]],
    ) -> list[ActionReviewResult]:
        """Drive the interactive loop. `on_decision` is called per result
        so the runner can persist incrementally and emit progress events."""
```

### `confirmation/runner.py`

```python
class ConfirmationRunner:
    def __init__(
        self,
        *,
        filter: Filter,
        mode: ReviewMode,
        renderer: Renderer,
        repo: RecordingRepository,
        threshold: float = 0.7,
        post_pass_hook: Callable[[UUID], Awaitable[None]] | None = None,
    ) -> None: ...

    async def run(self, recording_id: UUID) -> ReviewSummary:
        """Load recording → filter → mode.review (with on_decision = persist)
        → emit summary → invoke post_pass_hook (default: enqueue
        promote_silver_to_gold via M11.5 worker pool)."""
```

### `confirmation/__init__.py`

```python
from .runner import ConfirmationRunner
from .filters import default_filters, default_filter
from .modes import default_modes, default_mode
from .renderers import default_renderers, default_renderer
from .protocol import (
    ActionReviewResult, Decision, Filter, Renderer, ReviewMode, ReviewSummary,
)


def default_runner(
    *,
    repo: RecordingRepository,
    threshold: float = 0.7,
    arq_pool: ArqRedis | None = None,
    filter_name: str | None = None,
    mode_name: str | None = None,
    renderer_name: str | None = None,
) -> ConfirmationRunner:
    """Construct from registry names. Names default to Config values."""
```

### Per-module shape

Every filter / mode / renderer module exports exactly one class. Example (`filters/below_threshold.py`):

```python
class BelowThresholdFilter:
    name = "below_threshold"

    def select(self, recording, *, threshold):
        return [a for a in recording.actions if a.classification_confidence < threshold]
```

Same pattern for modes and renderers — single class per file, dependencies arrive via constructor or method args, no module-level state.

### Registry shape

```python
# filters/__init__.py
from .below_threshold import BelowThresholdFilter
from .by_intent import ByIntentFilter
from .failed_on_replay import FailedOnReplayFilter
from .unconfirmed_only import UnconfirmedOnlyFilter
from .since_date import SinceDateFilter

_FILTERS: dict[str, Callable[..., Filter]] = {
    "below_threshold": BelowThresholdFilter,
    "by_intent":       ByIntentFilter,
    "failed_on_replay":FailedOnReplayFilter,
    "unconfirmed_only":UnconfirmedOnlyFilter,
    "since_date":      SinceDateFilter,
}

def default_filters() -> dict[str, Callable[..., Filter]]:
    return dict(_FILTERS)

def default_filter(name: str | None = None, **kwargs) -> Filter:
    name = name or Config().confirmation_default_filter
    cls = _FILTERS[name]
    return cls(**kwargs)
```

Modes and renderers follow the same pattern.

## Behavior

### Runner flow

1. `recording = await repo.get_recording(recording_id)`. Raises if not found.
2. `candidates = filter.select(recording, threshold=self.threshold)`. If empty, render an empty `ReviewSummary` with "nothing to review" message and return.
3. Build `on_decision` closure that calls `repo.update_action_classification(...)` per-result and emits a structlog event. This is the persistence point — incremental writes so a Ctrl+C mid-pass keeps progress.
4. `results = await mode.review(candidates, renderer=self.renderer, on_decision=on_decision)`.
5. Aggregate into a `ReviewSummary`.
6. `renderer.render_summary(summary)` — print final tally.
7. If `post_pass_hook` is provided, call it (default wires to ARQ pool: `await arq_pool.enqueue_job("promote_silver_to_gold", recording_id=recording_id)`).
8. Return the summary.

### Default review modes

| Mode | Flow |
|---|---|
| `per_action` | iterate candidates one by one; render via `renderer.render_action`; prompt `[a]ccept / [r]elabel / [s]kip`; on relabel, prompt for `SemanticIntent` via `rich.prompt.Prompt.ask(choices=...)`; emit `ActionReviewResult` per action |
| `per_intent_batch` | group candidates by `semantic_intent`; for each group, render via `renderer.render_intent_batch`; prompt `[a]ccept all / [r]eview each / [s]kip group / [c]ustom relabel for whole group`; on review-each, fall back to `per_action` for that group |
| `overview` | render a single table of all candidates with confidence + intent + selector; prompt for filter refinement (`[a]ccept all confidence>=X / [r]eview rows N-M / [s]kip`); refines candidates and recurses |
| `diff_baseline` | accept a `baseline_at: datetime` parameter; only show actions whose `classification_reasoning` differs from the row's state at `baseline_at` (read from a small JSONL audit log if present, else fall back to "all candidates"); useful when re-classifying after a prompt change in M9 |

Each mode is a discrete file. The `per_intent_batch` mode demonstrates composition: it can call `PerActionMode().review(...)` for the relabel-each fallback, so modes are reusable.

### Default renderers

| Renderer | Fields shown per action |
|---|---|
| `compact` | sequence • intent • confidence • selector summary (test_id or role+name) • visible_text (first 40 chars). One row per action in a `rich.table.Table` |
| `detailed` | compact fields + full `element_context` (tag, attributes, parent_form_id, nearby_labels), payload (redacted), classification_reasoning, screenshot_path (if any from prior runs) |
| `side_by_side` | two columns: heuristic verdict (parsed from `[heuristic:<rule>]` prefix in reasoning per M7), LLM verdict (parsed from `[llm]` prefix per M9). When only one ran, the other column shows `—` |

Renderers are pure formatting — no I/O, no DB access. Easy to unit-test by rendering to a `Console(record=True)` and asserting on captured text.

### Persistence semantics

- Per-action partial updates via `RecordingRepository.update_action_classification(action_id, intent=..., user_confirmed=True, user_label=...)`. Each is a separate transaction so a long pass doesn't hold one write lock for minutes.
- The `user_label` field overrides `semantic_intent` from the user's POV; the original `semantic_intent` (from heuristic/LLM) stays in place so M11.5's `gold_classifier_accuracy_history` can compute "classifier said X, user said Y" diffs.
- After all decisions persist, runner enqueues `promote_silver_to_gold(recording_id=...)` via the ARQ pool (M11.5). If no pool is provided (e.g., in tests or offline mode), this step is a no-op with a structlog info log.

### Progress and interrupt handling

- Each `ActionReviewResult` is persisted immediately (within `on_decision`). Ctrl+C mid-pass keeps everything reviewed so far.
- The CLI command body (`commands/confirm.py`) wraps the runner via M8's `run_async` decorator, which catches `KeyboardInterrupt` and translates to `CLIError("interrupted", exit_code=130)`. The runner's `try/finally` flushes a final summary even on interrupt.
- Each `mode.review()` is responsible for its own internal cancellation handling: `per_action` checks for KeyboardInterrupt at every prompt; `per_intent_batch` finishes the current intent group before re-checking. Document this in each mode's docstring.

### Adding a new review mode (worked example: `bulk_accept_high_confidence`)

A pre-pass that auto-accepts everything above a high threshold, then hands the rest to `per_action`:

1. Create `src/rpa_recorder/confirmation/modes/bulk_accept_high_confidence.py`:
   ```python
   class BulkAcceptHighConfidenceMode:
       name = "bulk_accept_high_confidence"

       def __init__(self, auto_accept_threshold: float = 0.95) -> None:
           self._threshold = auto_accept_threshold
           self._fallback = PerActionMode()

       async def review(self, candidates, *, renderer, on_decision):
           auto, manual = [], []
           for a in candidates:
               (auto if a.classification_confidence >= self._threshold else manual).append(a)
           results = []
           for a in auto:
               result = ActionReviewResult(
                   action_id=a.id, decision=Decision.ACCEPT,
                   new_label=None, reviewed_at=datetime.now(UTC),
               )
               await on_decision(result)
               results.append(result)
           console.print(f"Auto-accepted {len(auto)}; reviewing {len(manual)}.")
           results.extend(await self._fallback.review(manual, renderer=renderer, on_decision=on_decision))
           return results
   ```
2. Register in `modes/__init__.py:_MODES` dict.
3. Add `tests/test_confirmation_modes.py::test_bulk_accept_high_confidence_*`.

No edits to runner, renderers, filters, or other modes. The new mode reuses `PerActionMode` for the manual portion — modes are composable.

### Adding a new filter (worked example: `recording_intent_balance`)

To rebalance training data for `gold_training_data.parquet`:

1. Create `filters/recording_intent_balance.py` selecting actions where the recording has fewer than N confirmed examples of that intent.
2. Add to `_FILTERS`.
3. Test.

Same pattern.

## Concurrency

This is interactive single-user CLI. No concurrency primitives needed at the M11 layer. The constraints we honor:

- **Async DB session** via M5's `get_session()` — repository updates are awaited.
- **`rich.prompt.Prompt.ask` is synchronous.** Calling it inside an `async def` blocks the loop, but that's fine here: the user is the only "task" the loop has to serve. Don't wrap in `asyncio.to_thread` — that adds cost without benefit and complicates Ctrl+C handling.
- **Per-action persistence** is awaited inline (not fan-out). Order matters for the audit log; sequential is correct.
- **Post-pass `enqueue_job` is non-blocking** — we don't `await` the worker's completion, just the enqueue. The hourly cron also runs gold promotion, so a missed enqueue self-heals within the hour.

The runner is **per-process, per-session** — no shared mutable state across sessions. Two terminals running `rpa confirm <id>` against the same recording would conflict at the DB level (concurrent updates to the same row); SQLite serializes via the WAL lock. Document the recommendation: review one recording in one terminal at a time.

## Medallion / worker integration

| Layer | Effect |
|---|---|
| Bronze | none directly — the user's decision is a structured event, not a raw artifact. (Could optionally write a `data/bronze/reviews/<recording-id>.jsonl` audit log if `Config.confirmation_audit_bronze=True`; default off.) |
| Silver | per-action `RecordedActionRow.user_confirmed` and `user_label` updated via `RecordingRepository.update_action_classification`. The original `semantic_intent` is preserved so accuracy comparisons remain possible |
| Cold gold | the user-confirmed labels feed `gold_training_data.parquet` via M11.5's `recompute_training_data` (filters where `user_confirmed=True`); also drives `gold_classifier_accuracy_history` (joins `semantic_intent` vs `user_label`) |
| Worker | runner enqueues `promote_silver_to_gold(recording_id=...)` (M11.5) at end of pass so dashboards refresh immediately rather than waiting for the hourly cron |
| FastAPI | M12 may add a `POST /recordings/{id}/confirmations` HTTP endpoint that mirrors this CLI flow for a future web UI. The same `ConfirmationRunner` core can be used (just substitute the renderer + mode for HTTP-friendly variants); M11 keeps the architecture web-ready |

## Integration points

| Touch | File | How |
|---|---|---|
| M2 → M11 | [src/rpa_recorder/models/actions.py](../src/rpa_recorder/models/actions.py) | reads `RecordedAction.classification_confidence`, `semantic_intent`, `user_confirmed`, `user_label`, `classification_reasoning` |
| M5 → M11 | [src/rpa_recorder/storage/repositories.py](../src/rpa_recorder/storage/repositories.py) | reads via `get_recording`; writes via new `update_action_classification` method |
| M8 → M11 | [src/rpa_recorder/cli/commands/__init__.py](../src/rpa_recorder/cli/commands/__init__.py) | adds `from . import confirm` to register the command |
| M9 → M11 | `Classification.source` attribution (`heuristic:<rule>` / `llm`) parsed by `side_by_side` renderer to populate columns |
| M10 → M11 | `failed_on_replay` filter joins `RecordedActionRow` against `ExecutionAttemptRow` to find actions that drove a recovery during replay |
| M11 → M11.5 | end-of-pass enqueue of `promote_silver_to_gold(recording_id=...)`; `gold_training_data.parquet` reads the user-confirmed labels |
| M11 → M12 | the same `ConfirmationRunner` can be invoked from a `POST /recordings/{id}/confirmations` HTTP endpoint with a different renderer/mode |

## Models / DB rows used

- **Reads:** `Recording`, `RecordedAction`, `ExecutionAttempt` (for `failed_on_replay` filter; M2/M5).
- **Writes:** updates `RecordedActionRow.user_confirmed`, `user_label` (and optionally `semantic_intent` if user explicitly relabels). No new rows or schema changes.
- **Optional bronze:** `data/bronze/reviews/<recording-id>.jsonl` audit log (off by default; enable via `Config.confirmation_audit_bronze=True`).

## Tests

`tests/test_confirmation_protocol.py`:
- `test_action_review_result_round_trips`.
- `test_review_summary_computes_totals`.
- `test_decision_enum_values`.

`tests/test_confirmation_filters.py`:
- `test_below_threshold_selects_only_below(threshold=0.7)` — seed actions at 0.5/0.7/0.9; selects 0.5 only.
- `test_by_intent_selects_matching_intent` — `intent=SemanticIntent.SEARCH` returns only those.
- `test_failed_on_replay_joins_executions(seeded_db)` — actions that have at least one failed `ExecutionAttempt`.
- `test_unconfirmed_only_filters_already_confirmed` — actions with `user_confirmed=True` excluded.
- `test_since_date_filter` — actions classified after a cutoff.

`tests/test_confirmation_renderers.py`:
- `test_compact_renderer_table_columns` — render to `Console(record=True)`; assert column headers.
- `test_detailed_renderer_redacts_sensitive_payloads` — input with `is_sensitive=True` → `***` in output.
- `test_side_by_side_parses_heuristic_and_llm_sources` — reasoning string `"[heuristic:login] ... ; [llm] ..."` produces two-column display with both verdicts.
- `test_compact_renderer_truncates_long_visible_text` — 200-char text → 40-char truncation with ellipsis.

`tests/test_confirmation_modes.py`:
- `test_per_action_mode_dispatches_decision_per_input(monkeypatch)` — patch `Prompt.ask` with scripted responses `["a", "r", "s"]`; assert three `ActionReviewResult`s with matching decisions.
- `test_per_action_mode_handles_relabel(monkeypatch)` — patch sequence `["r", "search"]`; result has `decision=RELABEL, new_label=SEARCH`.
- `test_per_action_mode_persists_via_on_decision(mock_repo)` — assert `on_decision` called once per action with the right result.
- `test_per_intent_batch_groups_by_intent(monkeypatch)` — three actions across two intents; `Prompt.ask` returns "a" for both groups; assert all three accepted.
- `test_per_intent_batch_falls_back_to_per_action(monkeypatch)` — group has user choosing "r" (review each); assert each action prompted individually.
- `test_overview_mode_lists_then_refines(monkeypatch)` — overview table → user picks "accept all >=0.5" → high-confidence accepted, lower-confidence falls to per-action.
- `test_diff_baseline_only_shows_changed` — seed audit log with a previous run; only actions whose intent changed since are surfaced.

`tests/test_confirmation_runner.py`:
- `test_runner_returns_summary_with_correct_totals(mock_repo, monkeypatch)` — drive 5 candidates, 3 accept / 1 relabel / 1 skip; summary matches.
- `test_runner_persists_each_decision_incrementally(mock_repo)` — assert `update_action_classification` called per result, not in one batch at the end.
- `test_runner_enqueues_promote_silver_to_gold_on_completion(mock_arq_pool)` — pool's `enqueue_job` called with `("promote_silver_to_gold", recording_id=...)`.
- `test_runner_skips_post_pass_hook_when_no_pool(caplog)` — no pool → structlog info log, no enqueue.
- `test_runner_handles_keyboard_interrupt_mid_pass(monkeypatch)` — patch mode to raise `KeyboardInterrupt` after 2 results; runner persists those 2, returns partial summary, re-raises so the CLI run_async wrapper translates to exit 130.

`tests/test_cli_confirm.py` (E2E with `CliRunner`):
- `test_confirm_against_seeded_recording(seeded_db)` — `runner.invoke(app, ["confirm", str(rec_id)], input="a\nr\nlogin\ns\n")` exits 0; output contains "1 accepted, 1 relabeled, 1 skipped"; DB rows reflect changes.
- `test_confirm_with_filter_flag(seeded_db)` — `--filter by_intent --intent search`; only SEARCH actions surfaced.
- `test_confirm_with_mode_flag(seeded_db)` — `--mode per_intent_batch`; output shows intent groupings.
- `test_confirm_unknown_recording_id` — bad UUID → exit 1, stderr "Recording not found".

Coverage target: **≥85%** on the `confirmation/` package.

## Known pitfalls

- **`rich.prompt.Prompt.ask` blocks the loop.** This is intentional and fine in interactive single-user CLI. Don't wrap in `asyncio.to_thread` — it adds latency, complicates Ctrl+C handling, and offers no benefit when the loop has no other work. Document this clearly so future async-purists don't "fix" it.
- **Per-action transactions.** Each `update_action_classification` is its own commit so a long pass doesn't hold one write lock. Trade-off: 100 actions = 100 transactions = more `BEGIN` / `COMMIT` overhead, but on SQLite WAL mode the cost is negligible (<1 ms each). Don't batch into one transaction — Ctrl+C-mid-pass would lose all reviewed actions.
- **`user_label` vs `semantic_intent` semantics.** When the user relabels, write to `user_label` and **also** update `semantic_intent` to the new value (so subsequent reads use the user's truth without parsing two fields). The original classifier verdict is preserved in `classification_reasoning` (which already includes the heuristic rule name and/or LLM verdict). This is important for M11.5's `gold_classifier_accuracy_history` to compute classifier-vs-truth diffs.
- **Two-terminal review of same recording.** Concurrent updates to the same row serialize via the SQLite WAL lock; the second terminal sees a brief delay but no data loss. Document the recommendation: one reviewer per recording at a time.
- **`CliRunner` and `Prompt.ask`.** Typer's testing CliRunner sends `input=` to stdin, which `Prompt.ask` reads correctly when invoked from a non-tty context. But `Prompt.ask(choices=[...])` repeats the prompt on invalid input — scripted tests must provide valid inputs only. Document and enforce in tests.
- **`rich.live.Live` doesn't capture in `Console(record=True)`.** Renderers that use Live for interactive overview must also expose a non-Live fallback path for testing. Or: skip Live entirely in `overview` mode and use a plain `print` + paginate-on-demand approach. Recommended: skip Live; tests stay easy.
- **Filter signature variations.** Some filters need extra params (`by_intent` needs `intent`, `since_date` needs `cutoff`). The registry pattern (`default_filter(name, **kwargs)`) accepts kwargs; document each filter's expected kwargs in its module docstring. Tests assert the kwargs surface in the CLI flags.
- **Post-pass enqueue race with cron.** The hourly `promote_silver_to_gold` cron may fire mid-pass; user's in-progress reviews may not show up until the *next* tick. M11.5's distributed Redis lock prevents two simultaneous gold runs, so this is benign — just clarify in user docs that "your review will reflect in the dashboard within ~1 minute of completion" not "instantly".
- **`CLIError("interrupted")` semantics.** When the user hits Ctrl+C mid-`Prompt.ask`, KeyboardInterrupt propagates up. The runner's `try/finally` flushes a partial summary before re-raising. M8's `run_async` then translates to exit 130. Tests verify the partial summary printed.
- **PEP 758 except syntax.** Python 3.14 allows parens-less `except A, B:`. Style choice.

## Commit

`feat(confirmation): add modular review pipeline with pluggable filters / modes / renderers`

Body: implements `rpa confirm <id>` as a thin Typer wrapper around a `ConfirmationRunner` with three plugin axes — `Filter` (which actions need review), `ReviewMode` (how the user is walked through them), `Renderer` (how each action is presented). Default rule set: `BelowThresholdFilter` + `PerActionMode` + `CompactRenderer`. Per-action persistence so Ctrl+C-mid-pass keeps progress; end-of-pass enqueues `promote_silver_to_gold` via M11.5's ARQ pool so dashboards reflect new labels immediately. New `RecordingRepository.update_action_classification` method for the partial updates. Adding a new filter / mode / renderer = single new module + registry entry + unit test. The architecture also keeps M12's potential web-UI flow trivial: substitute renderer + mode, reuse the runner core.

## Critical files

- `src/rpa_recorder/cli/commands/confirm.py` — thin Typer wrapper
- `src/rpa_recorder/confirmation/protocol.py` — Filter / ReviewMode / Renderer Protocols + `Decision` / `ActionReviewResult` / `ReviewSummary` Pydantic
- `src/rpa_recorder/confirmation/runner.py` — `ConfirmationRunner` orchestrator
- `src/rpa_recorder/confirmation/{filters,modes,renderers}/__init__.py` — registries
- The per-rule modules under those subdirs
- `src/rpa_recorder/storage/repositories.py` — new `update_action_classification` method
- `tests/test_confirmation_*.py` and `tests/test_cli_confirm.py`
