# M3 — BrowserSession

**Status:** completed

**Commit:** `3a18d0c feat(browser): add BrowserSession async context manager`

**Source:** `.claude/plans/bootstrap.md` (Browser Layer Specification — `browser/session.py`).

## Goal

A clean async context manager that owns the Playwright lifecycle: starts Playwright, launches Chromium, creates a `BrowserContext` and a `Page`, optionally records a HAR and a trace, and tears everything down in the right order.

## What shipped

### `src/rpa_recorder/browser/session.py`

`class BrowserSession`:

```python
def __init__(
    self,
    *,
    headless: bool = False,
    storage_state: str | None = None,
    viewport: dict[str, int] | None = None,
    locale: str = "en-US",
    timezone_id: str = "UTC",
    trace_path: str | None = None,
    har_path: str | None = None,
) -> None: ...

async def __aenter__(self) -> Self: ...
async def __aexit__(self, exc_type, exc_val, exc_tb) -> None: ...

@property
def page(self) -> Page: ...     # raises RuntimeError if not entered
@property
def context(self) -> BrowserContext: ...
```

### Lifecycle ordering

`__aenter__` uses an `AsyncExitStack` to push cleanup callbacks in the right order:

1. `async_playwright()` enters as an async context.
2. `browser = await pw.chromium.launch(...)`; `stack.push_async_callback(browser.close)`.
3. `context = await browser.new_context(**kwargs)`; `stack.push_async_callback(context.close)` — closing the context is what flushes the HAR file when `record_har_path` was passed.
4. If `trace_path` is set: `context.tracing.start(screenshots=True, snapshots=True, sources=True)`; push a callback that calls `tracing.stop(path=trace_path)` so the zip is written.
5. `page = await context.new_page()`.

Cleanup order on exit (reverse of push): trace stop → context close (HAR flushed) → browser close → playwright stop. If anything in setup raises, `stack.aclose()` rolls back partial state before re-raising.

### Implementation choices

- **`Self` return type on `__aenter__`** so subclasses type-narrow correctly.
- **`viewport: dict[str, int]`** from the public API; passed via `**` unpack into `context_kwargs` to bypass mypy's `ViewportSize` TypedDict strictness without widening the public signature.
- **HAR is implicit** — setting `record_har_path` on `new_context()` is enough; Playwright writes the file when the context closes. We don't manage the file ourselves.
- **`TracebackType` under `TYPE_CHECKING`** because Python 3.14 lazy annotations make runtime imports unnecessary for annotation-only symbols.

## Tests

`tests/test_session.py` — 7 tests, 5 integration:

1. `test_page_property_raises_outside_context` — accessing `.page` before `__aenter__` raises.
2. `test_context_property_raises_outside_context`.
3. `test_session_opens_and_closes_cleanly` (`@pytest.mark.integration`) — open, navigate to `about:blank`, close.
4. `test_session_uses_custom_viewport` — `viewport={"width": 800, "height": 600}` honored.
5. `test_session_writes_trace_zip` — `trace_path` produces a non-empty zip on disk.
6. `test_session_writes_har_file` — `har_path` produces a non-empty HAR on disk.
7. `test_session_resets_after_exit` — after `__aexit__`, `.page` and `.context` raise again.

Integration tests use real headless Chromium (installed via `uv run playwright install chromium`).

## Critical files

- `src/rpa_recorder/browser/session.py`
- `tests/test_session.py`
