# M4 — Recorder + injected JS

**Status:** completed

**Commit:** `7605829 feat(browser): add Recorder with page-side capture script`

**Source:** `.claude/plans/bootstrap.md` (`browser/recorder.py`, `assets/recorder_inject.js`) and the page→Python payload schema in `.claude/plans/data-capture.md §1`.

## Goal

Record user-driven browser actions with rich semantic context: ARIA role, accessible name, `data-testid`, tag, attributes, visible text, bounding box, parent form id, nearby labels — plus a network log and main-frame navigations. Output is a `Recording` aggregating `RecordedAction` rows.

## What shipped

### `src/rpa_recorder/assets/recorder_inject.js`

Page-side script, dependency-free, attached via `page.add_init_script` so it runs in every frame on every navigation. IIFE-wrapped, idempotent (`window.__rpaInjected` guard).

- Capture-phase listeners on `click`, `input`, `change`, `keydown` (Enter only).
- Each event builds an envelope matching `data-capture.md §1`:
  ```json
  {"event_type", "target": {role, accessible_name, test_id, tag, attributes,
   css, xpath, visible_text, bounding_box, is_visible, is_enabled,
   parent_form_id, nearby_labels}, "payload", "frame_url", "page_title",
   "viewport", "timestamp_ms"}
  ```
- Helpers: `inferRole` (tag + `type` → ARIA role), `accessibleName` (aria-label → labelledby → label → placeholder → title → text), `uniqueCss` (id → tag.classes:nth-of-type chain), `xpathOf` (tag[idx] chain), `attrs` (capped at 4 KB), `nearbyLabels` (label[for=id] + closest label).
- After successful `await window.__rpa_capture(env)` it increments `window.__rpaCaptureCount` so tests can deterministically wait via `page.wait_for_function("() => window.__rpaCaptureCount >= N")`.

### `src/rpa_recorder/browser/recorder.py`

`class Recorder`:

```python
def __init__(
    self,
    page: Page,
    *,
    name: str = "recording",
    starting_url: str | None = None,
) -> None: ...

async def start(self) -> None: ...
async def stop(self) -> None: ...
def get_recording(self) -> Recording: ...
```

`start()`:
1. `await page.expose_function("__rpa_capture", self._on_capture)`.
2. `await page.add_init_script(script=...)`.
3. `await page.evaluate(script)` for the document already loaded (suppressed on failure).
4. Hooks `page.on("request"|"response"|"framenavigated")`.

Capture pipeline:
- `_on_capture(raw)` validates → `_build_action(raw)` → appends to `_actions`. Pydantic `ValidationError`/`ValueError`/`TypeError` are swallowed so a malformed envelope can't crash the page.
- Event-type → `ActionType` mapping: `click → CLICK`, `input → INPUT`, `change` on `<select> → SELECT` else `INPUT`, `keydown → KEY_PRESS` (dict payload).
- `_on_request` appends a `NetworkEvent`; `_on_response` patches `status` + `response_summary` on the most-recent matching row.
- `_on_framenavigated` (main frame only, dedup by URL) emits a `NAVIGATE` action with `NavigatePayload`.

Cleanup:
- `stop()` flips `_stopped`, removes the request/response/framenavigated listeners (`with suppress(KeyError, ValueError)` to tolerate already-detached state).

Concurrency: handlers do not `await` between mutating `_sequence` and appending to `_actions`, so under asyncio's single-threaded model captures stay ordered without an explicit lock.

### Asset packaging

- `src/rpa_recorder/assets/__init__.py` makes `assets/` an importable subpackage so `importlib.resources.files("rpa_recorder.assets").joinpath("recorder_inject.js").read_text()` resolves the script at runtime.

### Type-import compromise

Playwright introspects listener-handler signatures via `inspect.signature()`, which forces annotation evaluation. `Frame`, `Page`, `Request`, `Response` are runtime-imported (with a `# noqa: TC002` to silence ruff) rather than gated under `TYPE_CHECKING`.

## Tests

`tests/test_recorder.py` — 5 tests, 3 integration:

1. `test_recorder_captures_click` — click on `#save`, asserts selector role/accessible_name/test_id/css/xpath, element_context tag/parent_form_id/visibility/enabled, viewport, frame_url.
2. `test_recorder_redacts_sensitive_input` — `fill("#email")` + `fill("#password")` → asserts `is_sensitive=True` from `type=password`, raw value preserved, `model_dump(context={"redact_secrets": True})` swaps in `***REDACTED***`.
3. `test_recorder_emits_navigate_on_main_frame` — `goto(file://fixture.html)` → at least one NAVIGATE action with `NavigatePayload(url=...)`.
4. `test_get_recording_before_start_raises` — unit-style.
5. `test_double_start_raises` — guards against re-exposing the binding.

Tests use `tmp_path` to write a static HTML fixture (form with email/password/save button) and `page.wait_for_function("() => window.__rpaCaptureCount >= N")` for deterministic waits — no `sleep()`.

## Critical files

- `src/rpa_recorder/assets/recorder_inject.js`
- `src/rpa_recorder/assets/__init__.py`
- `src/rpa_recorder/browser/recorder.py`
- `tests/test_recorder.py`
