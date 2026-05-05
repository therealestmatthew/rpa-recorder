# M10 — Recovery engine + strategies (modular pipeline)

**Status:** pending

**Source:** [.claude/plans/bootstrap.md](../.claude/plans/bootstrap.md) §Recovery; [build-plan.md](build-plan.md) §Concurrency conventions; [_archive/m6-executor.md](_archive/m6-executor.md) §Notes for M10 (the integration hook). Replaces the original sketch with a per-strategy module layout, failure-mode preconditions, post-recovery verification, and explicit composition with M9's LLM primitives.

## Goal

Wire `Executor._attempt_recovery` (currently a stub returning `None` — see [src/rpa_recorder/browser/executor.py](../src/rpa_recorder/browser/executor.py)) to a strategy pipeline so replays can heal common, well-understood failures (timing flakes, modals, off-screen elements, iframe targets, selector drift) before giving up. Each strategy is a small, independently-testable module that:

1. Declares which `FailureMode`s it applies to (so the engine doesn't waste time running strategies that obviously can't help).
2. Receives the failed `ActionExecution`, the live `Page`, the original `RecordedAction`, and a `RecoveryContext` (shared LLM client, semaphore, bronze writer).
3. Returns a `RecoveryDecision` — applied/not-applied, succeeded/failed, with optional new `ElementSelector`, rationale, and per-strategy artifacts written to bronze.

The `RecoveryEngine` filters strategies by failure mode, runs survivors in cost order (cheap → expensive), verifies success after each (re-resolves the selector — defends against false positives like hallucinated LLM selectors), and stops on the first verified-successful strategy. Adding a new strategy = one new module + a registry entry + a unit test, no engine edits.

## Files

### Create

- `src/rpa_recorder/recovery/__init__.py` — public API: `RecoveryEngine`, `default_engine`, `RecoveryDecision`, `Strategy`
- `src/rpa_recorder/recovery/protocol.py` — `Strategy` Protocol, `RecoveryContext`, `RecoveryDecision` Pydantic
- `src/rpa_recorder/recovery/engine.py` — `RecoveryEngine` orchestrator + verifier
- `src/rpa_recorder/recovery/strategies/__init__.py` — explicit registry: `default_strategies()`
- `src/rpa_recorder/recovery/strategies/wait_and_retry.py`
- `src/rpa_recorder/recovery/strategies/scroll_into_view.py`
- `src/rpa_recorder/recovery/strategies/dismiss_modal.py`
- `src/rpa_recorder/recovery/strategies/frame_switch.py`
- `src/rpa_recorder/recovery/strategies/llm_reselect.py`
- `src/rpa_recorder/recovery/prompts/__init__.py`
- `src/rpa_recorder/recovery/prompts/reselect_v1.py` — implements M9's `PromptStrategy` for selector reselection
- `src/rpa_recorder/recovery/parsers/__init__.py`
- `src/rpa_recorder/recovery/parsers/selector_tool_use.py` — implements M9's `ResponseParser` returning `ElementSelector` instead of `ClassifyCandidate`
- `tests/test_recovery_protocol.py`
- `tests/test_recovery_engine.py`
- `tests/test_recovery_wait_and_retry.py`
- `tests/test_recovery_scroll_into_view.py`
- `tests/test_recovery_dismiss_modal.py`
- `tests/test_recovery_frame_switch.py`
- `tests/test_recovery_llm_reselect.py`
- `tests/test_recovery_e2e.py` — full executor + recovery on a fixture page (`@pytest.mark.integration`)

### Modify

- `src/rpa_recorder/browser/executor.py` — replace `_attempt_recovery` stub with `RecoveryEngine.attempt(...)` invocation; thread `RecoveryContext` through executor's constructor
- `src/rpa_recorder/recovery/strategies.py` — **delete** (the original single-file scaffold from M1; superseded by the package)
- `src/rpa_recorder/config.py` — add `recovery_max_depth: int = 1`, `recovery_strategy_timeout_s: float = 10.0`, `recovery_llm_timeout_s: float = 30.0`

## Public API

### `recovery/protocol.py`

```python
class RecoveryContext(BaseModel):
    """Carried into every Strategy.attempt call. Built once per replay
    by the executor; reused across all actions in the run."""
    llm_backend: LLMBackend | None = None        # M9 contract; None disables LLM strategies
    llm_prompt: PromptStrategy | None = None     # default ReselectV1Prompt
    llm_parser: ResponseParser | None = None     # default SelectorToolUseParser
    llm_retry: RetryPolicy | None = None         # default ExponentialBackoffRetry
    llm_cache: ResponseCache | None = None
    llm_semaphore: asyncio.Semaphore | None = None  # shared with M9
    bronze: BronzeWriter | None = None           # M6.5 contract; None disables bronze writes
    budget: BudgetGuard | None = None            # shared with M9
    max_depth: int = 1                            # cap recursive recovery


class RecoveryDecision(BaseModel):
    """Strategy verdict. The engine consults `applicable` and `succeeded`."""
    applicable: bool                              # did this strategy's preconditions match?
    succeeded: bool                               # did the page state actually fix?
    new_selector: ElementSelector | None = None   # surfaced to ActionExecution.recovery
    rationale: str
    artifacts: list[str] = Field(default_factory=list)  # bronze paths written
    duration_ms: int


class Strategy(Protocol):
    name: str
    applicable_modes: frozenset[FailureMode]      # FailureMode enum from M2
    cost_tier: int                                 # 0 = cheap (sub-second), 5 = expensive (LLM)

    async def attempt(
        self,
        *,
        failed: ActionExecution,
        page: Page,
        original: RecordedAction,
        ctx: RecoveryContext,
    ) -> RecoveryDecision: ...
```

### `recovery/engine.py`

```python
class RecoveryEngine:
    def __init__(self, strategies: Sequence[Strategy]) -> None: ...

    async def attempt(
        self,
        *,
        failed: ActionExecution,
        page: Page,
        original: RecordedAction,
        ctx: RecoveryContext,
        depth: int = 0,
    ) -> RecoveryAction | None:
        """Run applicable strategies in cost order, stop on first verified
        success. Returns a RecoveryAction (M2 model) for the executor to
        attach to ActionExecution.recovery, or None if all strategies
        declined or failed.

        Recursion depth is bounded by ctx.max_depth (default 1) — recovery
        from a recovery is disabled by default.
        """
```

### `recovery/__init__.py`

```python
from .engine import RecoveryEngine
from .protocol import RecoveryContext, RecoveryDecision, Strategy
from .strategies import default_strategies


def default_engine() -> RecoveryEngine:
    """Curated default strategy roster, sorted by cost_tier ascending:
       wait_and_retry → scroll_into_view → dismiss_modal → frame_switch → llm_reselect."""
    return RecoveryEngine(default_strategies())
```

### Per-strategy module shape

Every strategy module exports exactly one class. Example (`strategies/dismiss_modal.py`):

```python
class DismissModalStrategy:
    name = "dismiss_modal"
    applicable_modes = frozenset({
        FailureMode.ELEMENT_NOT_INTERACTABLE,
        FailureMode.UNEXPECTED_MODAL,
    })
    cost_tier = 2

    async def attempt(self, *, failed, page, original, ctx):
        started = time.monotonic()
        try:
            close_locator = page.locator(
                "[role=dialog] [aria-label*=close i],"
                " [role=dialog] button:has-text('Close'),"
                " [role=dialog] [aria-label*=dismiss i]"
            )
            if await close_locator.count() == 0:
                return RecoveryDecision(
                    applicable=True, succeeded=False,
                    rationale="no dialog close affordance found",
                    duration_ms=int((time.monotonic() - started) * 1000),
                )
            await close_locator.first.click(timeout=ctx_timeout_ms())
            return RecoveryDecision(
                applicable=True, succeeded=True,
                rationale="dismissed modal via close affordance",
                duration_ms=int((time.monotonic() - started) * 1000),
            )
        except (PlaywrightError, asyncio.TimeoutError) as exc:
            return RecoveryDecision(
                applicable=True, succeeded=False,
                rationale=f"dismiss attempt failed: {exc}",
                duration_ms=int((time.monotonic() - started) * 1000),
            )
```

This shape is the contract for every strategy. No mutable state, no shared globals; all dependencies arrive via `ctx`.

### Registry shape

```python
# strategies/__init__.py
from .wait_and_retry import WaitAndRetryStrategy
from .scroll_into_view import ScrollIntoViewStrategy
from .dismiss_modal import DismissModalStrategy
from .frame_switch import FrameSwitchStrategy
from .llm_reselect import LLMReselectStrategy


def default_strategies() -> list[Strategy]:
    """Order is cost ascending. Engine still filters by applicable_modes
    before running."""
    return [
        WaitAndRetryStrategy(),       # cost_tier=0
        ScrollIntoViewStrategy(),     # cost_tier=1
        DismissModalStrategy(),       # cost_tier=2
        FrameSwitchStrategy(),        # cost_tier=2
        LLMReselectStrategy(),        # cost_tier=5
    ]
```

To add a strategy: create the module, append to this list, write a unit test. The engine never changes.

## Behavior

### Engine flow

1. **Filter by failure mode.** `failure = failed.attempts[-1].failure_mode`; keep only strategies where `failure in strategy.applicable_modes`. Log via structlog which strategies were filtered out and why.
2. **Sort by `cost_tier` ascending** (already pre-sorted in `default_strategies`, but the engine re-sorts so ad-hoc lists work).
3. **For each strategy** (sequential — recovery is *not* parallelized):
   - Apply per-strategy timeout via `asyncio.wait_for(strategy.attempt(...), timeout=Config.recovery_strategy_timeout_s)`.
   - If `decision.applicable is False`: skip, log debug.
   - If `decision.succeeded is False`: log info, continue to next.
   - If `decision.succeeded is True`: **verify** (see below). If verification fails, treat strategy as failed and continue.
4. **On first verified success**: return `RecoveryAction(strategy=name, rationale=..., succeeded=True, new_selector=decision.new_selector)`.
5. **All exhausted**: return `None`. The executor records `ActionExecution.status=FAILED`.

### Verification step (post-success defense)

After a strategy returns `succeeded=True`, the engine re-resolves the action's selector (using `new_selector` if the strategy provided one, otherwise the original) and confirms it now resolves to exactly one element via the same multi-strategy resolver M6 already uses. If verification fails, the strategy was wrong (hallucinated selector, side effect that didn't actually fix the issue) — the engine logs and falls through to the next strategy.

### Per-strategy behavior

| Strategy | Applies to | What it does |
|---|---|---|
| `wait_and_retry` (tier 0) | `TIMEOUT`, `ELEMENT_NOT_INTERACTABLE` | `await page.wait_for_timeout(500)`. No mutation, no new_selector — just gives slow SPAs more time. |
| `scroll_into_view` (tier 1) | `ELEMENT_NOT_INTERACTABLE` | If selector resolves but is off-screen / `is_visible=False`, calls `locator.scroll_into_view_if_needed()`. Pure-page op. |
| `dismiss_modal` (tier 2) | `ELEMENT_NOT_INTERACTABLE`, `UNEXPECTED_MODAL` | Locates `[role=dialog]` close affordances by aria-label / button text; clicks the first match. State-mutating — irreversible. |
| `frame_switch` (tier 2) | `ELEMENT_NOT_FOUND` | Walks `page.frames`; for each iframe, tries to resolve the original selector inside it. On match, returns a new `ElementSelector` with `frame_url` set so M6's executor targets the right frame. |
| `llm_reselect` (tier 5) | `ELEMENT_NOT_FOUND`, `ELEMENT_NOT_INTERACTABLE`, `UNKNOWN` | Builds a filtered DOM (≤5 KB; strip `<script>`, `<style>`, `<svg>`, comments, and any subtree without text/role); calls `ctx.llm_backend.complete(...)` via `ctx.llm_retry.execute(...)` with prompt from `ctx.llm_prompt` (default `ReselectV1Prompt`); parses with `ctx.llm_parser` (default `SelectorToolUseParser`) into a new `ElementSelector`. Caches via `ctx.llm_cache` keyed on `(model, prompt.version, sha256(filtered_dom + original_selector + failure_mode))`. Subject to `ctx.budget` and `ctx.llm_semaphore` (shared with M9, so total LLM concurrency stays bounded). |

### Adding a new strategy (worked example: `RetryWithLongerWaitStrategy`)

For slower SPAs where 500 ms isn't enough:

1. Create `src/rpa_recorder/recovery/strategies/retry_with_longer_wait.py`:
   ```python
   class RetryWithLongerWaitStrategy:
       name = "retry_with_longer_wait"
       applicable_modes = frozenset({FailureMode.TIMEOUT})
       cost_tier = 1

       def __init__(self, delay_s: float = 3.0) -> None:
           self._delay_s = delay_s

       async def attempt(self, *, failed, page, original, ctx):
           started = time.monotonic()
           await asyncio.sleep(self._delay_s)
           return RecoveryDecision(
               applicable=True, succeeded=True,
               rationale=f"waited {self._delay_s}s",
               duration_ms=int((time.monotonic() - started) * 1000),
           )
   ```
2. Add `RetryWithLongerWaitStrategy()` to the list in `strategies/__init__.py`.
3. Add `tests/test_recovery_retry_with_longer_wait.py` with a fixture that needs the longer wait.

The engine's verification step ensures this strategy's `succeeded=True` is real — if the element still isn't there after 3 s, the verifier fails it and the engine moves on to (e.g.) `llm_reselect`.

### Adding a new prompt for `LLMReselectStrategy`

LLMReselect's prompt is its own M9 `PromptStrategy` implementation in `recovery/prompts/reselect_v1.py`. To experiment with a different prompt (e.g., chain-of-thought reselection):

1. Create `recovery/prompts/reselect_cot.py`.
2. Pass it to `RecoveryContext(llm_prompt=ReselectCotPrompt())` from the executor wiring.

The cache key includes `prompt.version` so swapping prompts naturally invalidates entries — same pattern as M9 classification.

## Concurrency

Recovery is **inline within `replay_run`** (per M11.5's stance: not a separate ARQ job). The browser, page, and DB session are owned by the worker job. The engine itself is sequential — strategies run one at a time, stop on first success.

The only async-concurrency primitive recovery introduces is `LLMReselect`'s use of `ctx.llm_semaphore`, which is **shared with M9** (constructed once in `WorkerSettings.on_startup` and passed through both classifier and recovery contexts). Total LLM in-flight per worker = `Config.llm_max_concurrency` (default 5), regardless of whether calls come from classification or reselection.

Per-strategy timeouts (`Config.recovery_strategy_timeout_s`, default 10 s) prevent a stuck strategy from hanging the whole replay. `LLMReselect` has its own larger timeout (`Config.recovery_llm_timeout_s`, default 30 s) since LLM round-trips can legitimately take longer.

`Config.recovery_max_depth=1` means a recovery action that itself fails does **not** trigger a recursive recovery. The action records `FAILED` and the executor moves on.

## Medallion / worker integration

| Layer | Effect |
|---|---|
| Bronze | every `LLMReselect` call writes `data/bronze/llm/<call-id>.json` (full prompt + response) via `BronzeWriter.write_llm_call(...)`; pointer registered in `bronze_artifacts` with `kind="llm_call"`. Other strategies optionally write small diagnostic JSONs (e.g., `dismiss_modal` records the close affordance HTML it clicked) to `data/bronze/runs/<run_id>/attempts/<id>/recovery/<strategy>.json` |
| Silver | every recovery attempt produces a `LLMCallRow` (when LLM was used) with `called_for="recover"`. The `ActionExecution.recovery` field gets the surviving `RecoveryAction` |
| Cold gold | M11.5's `gold_classifier_accuracy` extends to track recovery effectiveness per-strategy: `gold_recovery_outcomes.parquet` (date, strategy, applicable_count, succeeded_count, mean_duration_ms). Computed by `recompute_recovery_outcomes` in `medallion/gold_cold.py` (M11.5 adds the column) |
| Worker | recovery runs inside `replay_run` — no separate job. Cancellation flag in `replay_run` is checked between strategy attempts so a user-initiated stop drops out of the recovery loop quickly |
| FastAPI | streamed events via Redis pub/sub: `recovery_started`, `recovery_succeeded`, `recovery_failed` per [data-capture.md §7](../.claude/plans/data-capture.md). Engine emits these via the executor's event-emitter callback (M12 hook) |

## Integration points

| Touch | File | How |
|---|---|---|
| M2 → M10 | [src/rpa_recorder/models/execution.py](../src/rpa_recorder/models/execution.py) | reads `ActionExecution`, `ExecutionAttempt`, `FailureMode`, writes `RecoveryAction` |
| M2 → M10 | [src/rpa_recorder/models/actions.py](../src/rpa_recorder/models/actions.py) | reads `RecordedAction`, `ElementSelector`, `ElementContext` |
| M6 → M10 | [src/rpa_recorder/browser/executor.py](../src/rpa_recorder/browser/executor.py) (`_attempt_recovery`) | swap stub for `RecoveryEngine.attempt(...)`; pass `RecoveryContext` from executor's constructor |
| M6.5 → M10 | `medallion/bronze.py` | `BronzeWriter.write_llm_call` and per-strategy diagnostic writes |
| M9 → M10 | `classifier/llm/protocol.py` | `LLMReselectStrategy` consumes `LLMBackend`, `PromptStrategy`, `ResponseParser`, `RetryPolicy`, `ResponseCache`, `BudgetGuard` directly |
| M9 → M10 | `classifier/llm/concurrency.py` | shared `asyncio.Semaphore` so total LLM in-flight is bounded across both classification and recovery |
| M10 → M11.5 | `replay_run` job's `RecoveryContext` is built from worker startup objects (one `LLMBackend`, one `BronzeWriter`, one shared `Semaphore`) |
| M10 → M12 | recovery event taxonomy emitted via the executor's event-emitter callback |

## Models / DB rows used

- **Reads:** `ActionExecution`, `ExecutionAttempt`, `RecordedAction`, `ElementSelector`, `ElementContext`, `FailureMode` (M2).
- **Writes:** `RecoveryAction` (assigned to `ActionExecution.recovery`), `LLMCallRow` (when `LLMReselect` runs, via M9 persistence), `BronzeArtifactRow` (for diagnostic blobs and LLM call JSON via M6.5).
- **Reuses M9 persistence**: `LLMReselectStrategy` doesn't reimplement bronze + silver writes — it constructs an `LLMClassifier`-like flow internally that goes through M9's `BronzeWriter.write_llm_call` + `LLMCallRow` insertion path.

## Tests

`tests/test_recovery_protocol.py`:
- `test_recovery_decision_round_trips_via_pydantic`.
- `test_strategy_protocol_has_required_attrs` — assert each default strategy has `name`, `applicable_modes`, `cost_tier`, `attempt`.

`tests/test_recovery_engine.py`:
- `test_engine_filters_by_applicable_modes` — fail with `TIMEOUT`; assert only `wait_and_retry` is invoked among defaults.
- `test_engine_runs_in_cost_tier_order` — fail with `ELEMENT_NOT_INTERACTABLE`; assert order is `wait_and_retry → scroll_into_view → dismiss_modal → llm_reselect`.
- `test_engine_stops_on_first_verified_success` — first strategy returns `succeeded=True` and verifier passes; second strategy not invoked.
- `test_engine_skips_strategy_if_verifier_rejects` — first strategy claims success but verifier fails (selector still doesn't resolve); second strategy invoked.
- `test_engine_per_strategy_timeout_caps_runtime(monkeypatch)` — patch a strategy to `sleep(60)`; engine cancels after `recovery_strategy_timeout_s=10`; logs and continues.
- `test_engine_returns_none_when_all_strategies_fail` — all return `succeeded=False` or applicable=False.
- `test_engine_respects_max_depth` — strategy's RecoveryAction triggers another action that fails; recovery is **not** invoked recursively (depth=1).
- `test_engine_emits_events_when_emitter_provided` — patch event emitter; assert `recovery_started`, `recovery_succeeded`, `recovery_failed` fire with strategy name.

`tests/test_recovery_wait_and_retry.py`:
- `test_wait_and_retry_succeeds_when_element_appears(browser_session)` — fixture page injects element after 200 ms; strategy waits 500 ms; verifier confirms; succeeded=True.
- `test_wait_and_retry_fails_when_element_never_appears(browser_session)` — element never appears; strategy returns `succeeded=False` (verifier defends).
- `test_wait_and_retry_only_applies_to_timeout_modes` — given `ELEMENT_NOT_FOUND`, applicable=False.

`tests/test_recovery_scroll_into_view.py`:
- `test_scrolls_to_offscreen_element(browser_session)` — fixture has element 5000 px below; selector resolves but `is_visible=False`; strategy scrolls; verifier confirms.
- `test_does_not_apply_when_element_already_visible(browser_session)` — applicable=True, succeeded=True trivially? Or applicable=False? Document the choice (recommend: applicable=True, succeeded=True with rationale "already visible") so the strategy still emits a recovery record.

`tests/test_recovery_dismiss_modal.py`:
- `test_dismiss_modal_clicks_close_button(browser_session)` — fixture has visible dialog with close `aria-label="Close"`; strategy clicks it; verifier confirms target underneath is now interactable.
- `test_dismiss_modal_no_dialog(browser_session)` — no dialog; succeeded=False with rationale.
- `test_dismiss_modal_close_button_not_clickable(browser_session)` — close button exists but is itself blocked; strategy returns succeeded=False (caught PlaywrightError).

`tests/test_recovery_frame_switch.py`:
- `test_frame_switch_finds_target_inside_iframe(browser_session)` — fixture page embeds an iframe whose document has the target; strategy returns `new_selector.frame_url=<iframe src>`; verifier resolves it inside the right frame.
- `test_frame_switch_skips_when_no_iframes` — applicable=True, succeeded=False.

`tests/test_recovery_llm_reselect.py`:
- `test_llm_reselect_uses_m9_backend(mock_anthropic, mock_bronze, mock_session)` — patch the SDK to return a tool-use response with a corrected selector; strategy returns `new_selector` matching; verifier resolves it; succeeded=True. Assert `BronzeWriter.write_llm_call` called once and `LLMCallRow` inserted with `called_for="recover"`.
- `test_llm_reselect_caches_response(in_memory_cache)` — call twice with same DOM + selector + failure_mode; second call hits cache, no SDK call.
- `test_llm_reselect_respects_budget_guard` — budget exceeded → returns succeeded=False with rationale; no SDK call.
- `test_llm_reselect_filters_dom_below_5kb` — fixture page has a 50 KB DOM; assert the prompt body is ≤5 KB after filtering (script/style/svg/comment removal).
- `test_llm_reselect_redacts_sensitive_payloads` — original action has `is_sensitive=True`; assert the prompt body does not contain the sensitive value.
- `test_llm_reselect_verifier_rejects_hallucinated_selector(mock_anthropic)` — SDK returns a valid-looking but non-matching selector; verifier fails; engine moves on.

`tests/test_recovery_e2e.py` (`@pytest.mark.integration`):
- `test_replay_recovers_from_modal_blocking_target` — fixture page shows a modal on first interaction that blocks the target button; replay's first attempt fails; recovery (`dismiss_modal`) closes the modal; replay's retry succeeds; `RunResult.status=RECOVERED`, `RecoveryAction.strategy="dismiss_modal"`.
- `test_replay_recovers_via_llm_when_selector_drifts(mock_anthropic)` — fixture page renames a button's `data-testid` between record and replay; recovery's `llm_reselect` returns the new selector; replay succeeds; `RecoveryAction.new_selector` populated.

Coverage target: **≥85%** on the `recovery/` package (some strategy code paths are integration-only and excluded).

## Known pitfalls

- **Verifier is mandatory.** `LLMReselect` can return a selector that *looks* right but doesn't resolve uniquely. Without the post-recovery verifier, the executor would commit to the bad selector and fail again later — possibly with a worse failure mode. Always verify before declaring a recovery succeeded.
- **`dismiss_modal` is irreversible.** Once a modal is closed, it can't be reopened to retry a different recovery. If `dismiss_modal` succeeds but the target is still blocked, the engine moves on, but page state has changed permanently. Document this in the strategy's docstring.
- **Recursive recovery disabled.** `Config.recovery_max_depth=1` means recovery on the recovery action's failure is suppressed. Set max_depth=2 only for very specific manual experiments — recursive recovery rarely helps and often loops.
- **Per-strategy timeout vs LLM call timeout.** `Config.recovery_strategy_timeout_s` (default 10 s) is the engine-level cap. `LLMReselect` has its own `Config.recovery_llm_timeout_s` (default 30 s) because LLM round-trips legitimately exceed 10 s. The engine respects whichever is larger for this specific strategy by inspecting the strategy's declared `cost_tier` (tier 5 strategies use the LLM timeout).
- **Shared LLM semaphore.** `RecoveryContext.llm_semaphore` must be the *same instance* as M9's `LLMClassifier.semaphore`. Otherwise total LLM in-flight can exceed `Config.llm_max_concurrency`. Build it once in `WorkerSettings.on_startup` and inject everywhere.
- **DOM filtering is lossy.** The 5 KB cap on filtered DOM means `LLMReselect` may not see the full context. Trade-off: bigger prompts cost more, time out more often, and don't necessarily help (the LLM struggles with 50 KB DOMs). 5 KB is a deliberate floor based on Anthropic's empirical sweet spot — adjust per workload.
- **Frame switch and selector frame_url.** When `frame_switch` returns a new selector with `frame_url`, the executor must resolve the locator inside that frame, not the main page. M6's executor needs a small extension: if `selector.frame_url` is set, use `page.frame(url=selector.frame_url).locator(...)` instead of `page.locator(...)`. M10 owns this executor change too — call it out in the executor migration section.
- **`PlaywrightError` swallowed in strategies.** Each strategy's `attempt` catches `PlaywrightError` and `asyncio.TimeoutError` and returns `succeeded=False`. Don't let a strategy bug crash the executor — the engine continues to the next one. But log the full exception via structlog so debug isn't impossible.
- **Cancellation propagation.** When the worker job is cancelled mid-recovery (user clicks "stop replay"), the current strategy's `await` should propagate `CancelledError` cleanly. Engine catches it at the boundary, persists `RunResult.status=CANCELLED`, and re-raises so ARQ records the cancellation.
- **Bronze writes during recovery.** `LLMReselect` writes a bronze blob per LLM call. If the bronze write itself fails (disk full, etc.), the strategy still uses the LLM's response — bronze is best-effort. Don't let bronze failure mask recovery success.
- **PEP 758 except syntax.** Python 3.14 allows parens-less `except A, B:`. Style choice.

## Commit

`feat(recovery): add modular strategy engine with wait / scroll / modal / frame / LLM-reselect`

Body: replaces the stub `Executor._attempt_recovery` with a full pipeline. Each strategy lives in its own module (`recovery/strategies/<name>.py`) with declared `applicable_modes`, `cost_tier`, and a single `attempt` method. The `RecoveryEngine` filters by failure mode, runs in cost-ascending order, and verifies success via post-recovery selector re-resolution before committing. `LLMReselectStrategy` composes M9's `LLMBackend`, `PromptStrategy`, `ResponseParser`, `RetryPolicy`, `ResponseCache`, `Semaphore`, and `BudgetGuard` — total LLM in-flight stays bounded across classification and recovery. Adding a new strategy = one new module + a registry entry + a unit test.

## Critical files

- `src/rpa_recorder/recovery/protocol.py` — Strategy + RecoveryContext + RecoveryDecision
- `src/rpa_recorder/recovery/engine.py` — engine + verifier
- `src/rpa_recorder/recovery/strategies/__init__.py` — registry
- `src/rpa_recorder/recovery/strategies/{wait_and_retry,scroll_into_view,dismiss_modal,frame_switch,llm_reselect}.py`
- `src/rpa_recorder/recovery/prompts/reselect_v1.py` and `parsers/selector_tool_use.py`
- `src/rpa_recorder/browser/executor.py` (wire engine in; add frame-aware locator path)
- `tests/test_recovery_*.py`
