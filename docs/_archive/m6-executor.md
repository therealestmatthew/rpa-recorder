# M6 — Executor with selector resolution

**Status:** completed

**Commit:** `10ca2d5 feat(browser): add Executor with multi-strategy selector resolution`

**Source:** `.claude/plans/bootstrap.md` (`browser/executor.py`).

## Goal

Replay a `Recording` against a Playwright `Page`, resolving each action's `ElementSelector` via a fixed strategy order, dispatching the action with auto-waiting, and on failure capturing screenshot + DOM html + accessibility tree to disk. Recovery is a hook stub (filled in by M10).

## What shipped

### `src/rpa_recorder/browser/executor.py`

`class Executor`:

```python
def __init__(
    self,
    page: Page,
    recording: Recording,
    *,
    screenshots_dir: Path,
    dom_dir: Path,
    parameter_values: dict[str, str] | None = None,
    run_id: UUID | None = None,
) -> None: ...

@property
def run_id(self) -> UUID: ...

async def run(self) -> RunResult: ...
```

### Selector resolution

`_resolve_selector(sel)` tries strategies in order and returns the first that resolves to **exactly one** element:

1. `test_id` → `page.get_by_test_id(sel.test_id)`
2. `role + accessible_name` → `page.get_by_role(sel.role, name=sel.accessible_name)`
3. `text_content` → `page.get_by_text(sel.text_content, exact=True)`
4. `css` → `page.locator(sel.css)`
5. `xpath` → `page.locator(f"xpath={sel.xpath}")`

Each candidate's `count()` is awaited; any `PlaywrightError` during count means "fall through to next." If no strategy matches uniquely, the executor raises `SelectorResolutionError` and the action is recorded as `ELEMENT_NOT_FOUND`.

The locator that won is also returned as a freshly-built `ElementSelector` so the attempt's `selector_used` field reflects exactly the strategy that succeeded — useful for telemetry and the M10 recovery layer.

### Typed action dispatch

`_dispatch_locator_action(action, locator)` covers:

- `CLICK` — `await locator.click(button=payload.button, modifiers=payload.modifiers)` if `ClickPayload`, else default click.
- `INPUT` — resolves the value via `_resolve_input_value` (parameter substitution if `is_parameterized`), `fill("")` if `clear_first`, then `fill(value)`.
- `SELECT` — `select_option(value=payload.values)` (requires `SelectPayload`).
- `KEY_PRESS` — `press(payload["key"])` from a dict payload, defaulting to `"Enter"`.
- `HOVER` — `locator.hover()`.

`_dispatch_navigate(action)` handles `NAVIGATE` actions outside the locator path: `page.goto(payload.url, wait_until=payload.wait_until)`.

Parameter substitution: when `action.is_parameterized` and `action.parameter_name in self._parameter_values`, the env-supplied value wins over the recorded one.

### Failure capture

On any `SelectorResolutionError`, `PlaywrightError`, or `ValueError` raised during `_execute_one`:

1. `_capture_failure(action, attempt_number)` writes:
   - `screenshots_dir / <run_id> / <seq>_<attempt>.png` via `page.screenshot()`
   - `dom_dir / <run_id> / <seq>_<attempt>.html` via `page.content()`
   - `dom_dir / <run_id> / <seq>_<attempt>.a11y.json` via `page.accessibility.snapshot()` (best-effort; not all Chromium builds expose it).
2. The `ExecutionAttempt` is populated with the paths, classified `failure_mode`, `error_message`, `selector_used`, and the per-attempt slices of `_console_log` and `_js_errors`.
3. `_attempt_recovery(action, attempt)` is called — currently a stub returning `None`. M10 plugs the `RecoveryEngine` in here.
4. The `ActionExecution.status` is `RECOVERED` if recovery succeeded, otherwise `FAILED`.

### Failure-mode classifier

`_classify_failure(error)` maps:
- `SelectorResolutionError` → `ELEMENT_NOT_FOUND`
- `PlaywrightTimeoutError` → `TIMEOUT`
- "not visible" / "not interactable" / "is hidden" in the message → `ELEMENT_NOT_INTERACTABLE`
- "navigation" in the message → `NAVIGATION_FAILED`
- otherwise → `UNKNOWN`

### Page-level listeners

Console messages and uncaught page errors are accumulated in `_console_log` and `_js_errors`. Each `_execute_one` snapshots indices before dispatch and slices the accumulated buffers per attempt — so an action's `console_log` shows only what the page produced during *that* action.

### Type-import compromise

`ConsoleMessage` is annotation-only on `_on_console` but Playwright introspects listener-handler signatures, so it's runtime-imported alongside `Error` and `TimeoutError` (which are runtime-used in `except` clauses). `Page` and `Locator` stay under `TYPE_CHECKING` since nothing introspects executor methods.

## Tests

`tests/test_executor.py` — 6 tests, 5 integration:

1. `test_executor_replays_click_recording` — fixture page with a button that flips `window.__clicked = true`; assert `RunResult.status == SUCCESS`, `selector_used.test_id == "save-btn"`, page-side flag flipped.
2. `test_executor_falls_back_through_selector_strategies` — selector with bogus `test_id` and bogus `css`, valid `role + accessible_name`. Assert success, `selector_used.role == "button"`, the bogus strategies are absent from `selector_used`.
3. `test_executor_captures_artifacts_on_failure` — recording targets non-existent `data-testid`; assert `RunResult.status == FAILED`, `failure_mode == ELEMENT_NOT_FOUND`, screenshot and DOM files exist on disk.
4. `test_executor_substitutes_parameters` — INPUT action with `is_parameterized=True, parameter_name="email"`; pass `parameter_values={"email": "alice@example.com"}`; assert the input field's value is `"alice@example.com"` after replay.
5. `test_executor_rejects_ambiguous_selector` — recording targets `.dup` (matches two spans); assert FAILED + `ELEMENT_NOT_FOUND`.
6. `test_selector_resolution_error_is_exception` — unit-style sanity check.

Tests build `Recording` instances programmatically (no dependency on M4's `Recorder`) so executor tests stay independent.

## Notes for M10

`_attempt_recovery(action, attempt)` is the integration hook. M10 will replace the stub with a `RecoveryEngine` invocation that walks `WaitAndRetryStrategy → DismissModalStrategy → LLMReselectStrategy` and returns the first successful `RecoveryAction`. The Executor already records the resulting `RecoveryAction` on the `ActionExecution` and flips the status to `RECOVERED` when `recovery.succeeded` is truthy — so M10 only needs to fill in the strategy implementations.

## Critical files

- `src/rpa_recorder/browser/executor.py`
- `tests/test_executor.py`
