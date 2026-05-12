# browser

Playwright-backed capture and replay (M3, M4, M6). Three concerns, three
files: a session lifecycle manager, a recorder that listens to page-side
events, and an executor that drives actions back into a fresh page.

## Layout

```
browser/
├── __init__.py
├── session.py    # BrowserSession — async context manager around chromium launch
├── recorder.py   # Recorder — attaches recorder/inject.js, drains events, writes bronze
└── executor.py   # Executor — multi-strategy selector resolution, action dispatch
```

## Conventions

- **One `BrowserSession` per replay.** Browser state is not concurrency-safe;
  each replay run creates and tears down its own session. ARQ caps
  `replay_queue` at `max_jobs=2` for this reason
  (see [`workers/README.md`](../workers/README.md)).
- **`storage_state` is opt-in.** Authenticated targets require a JSON
  storage state on disk passed to `BrowserSession(storage_state=...)`.
  Recorded sessions persist their final cookies+storage on close if
  `persist_storage_state=True`.
- **Recorder writes to bronze first.** The page-side
  [`page_scripts/recorder/inject.js`](../page_scripts/) emits envelopes
  that hit the in-memory `BoundedQueue` first, then the
  `BronzeStore` writer drains it. Silver rows are written from bronze
  later (M11.5 promotion job), not inline.
- **Executor resolves selectors in priority order.** `data-testid` >
  `aria-role+name` > stable CSS > positional XPath. The first that
  matches and is interactable wins; failures are recorded for
  recovery (see [`recovery/`](../recovery/)).
- **Errors in injected JS must not break the page.** Every script in
  `page_scripts/` wraps its body in a `try/catch` swallow.

## Adding a new browser feature

- **New page-side capture (e.g., richer DOM snapshot)** — add a script
  under [`page_scripts/recorder/`](../page_scripts/) and have
  `Recorder.start()` `add_init_script` it. Decode the envelope on the
  Python side and route through the existing bronze writer.
- **New executor action** — extend the dispatch table in `executor.py`
  keyed by `RecordedAction.action`. Add a unit test that mocks Playwright
  via `pytest-playwright`'s page fixture.

## See also

- [`docs/_archive/m3-browser-session.md`](../../../docs/_archive/m3-browser-session.md) — session milestone.
- [`docs/_archive/m4-recorder.md`](../../../docs/_archive/m4-recorder.md) — recorder milestone.
- [`docs/_archive/m6-executor.md`](../../../docs/_archive/m6-executor.md) — executor milestone.
- [`docs/m6.5-page-scripts-and-bronze.md`](../../../docs/m6.5-page-scripts-and-bronze.md) — bronze write seam.
- [`page_scripts/README.md`](../page_scripts/README.md) — injected JS conventions.
