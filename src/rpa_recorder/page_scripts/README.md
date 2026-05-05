# page_scripts

JavaScript that runs in the page context, organized by purpose. Loaded into
the Playwright `Page` via `load(...)` / `bundle(...)` from
`rpa_recorder.page_scripts`.

## Layout

```
page_scripts/
├── __init__.py            # load(), bundle()
├── recorder/              # capture-time scripts (run during recording)
│   ├── inject.js          # main capture script (uses shared/*)
│   ├── dom_snapshot.js    # full-DOM snapshot (M6.5 stub, M11.5 wires it)
│   └── a11y_tree.js       # accessibility tree dump (M6.5 stub)
├── replay/                # replay-time scripts (run during replay)
│   ├── locator_healing.js # in-page selector healing (M10 stub)
│   └── modal_detector.js  # detect unexpected modals (M10 stub)
└── shared/                # cross-cutting helpers used by both tiers
    ├── selectors.js       # CSS / XPath / role / attribute helpers
    └── text_utils.js      # trim, accessibleName
```

## Conventions

Every `.js` file in this tree:

- **Is an IIFE** wrapped in `(() => { ... })()` so it does not leak into the
  page's global scope.
- **Is idempotent** — guarded by a unique `window.__rpa<Name>Loaded` flag so
  Playwright's `add_init_script` (which reruns on every navigation) plus the
  one-shot `evaluate(script)` for the current document do not double-define.
- **Is dependency-free at file scope** — uses only browser-native APIs and,
  optionally, `window.__rpa.shared.*` exposed by other shared scripts.
- **Silently catches its own errors** — recording / replay must never break
  the page being automated.

Shared utilities expose themselves on `window.__rpa.shared.*`. Recorder and
replay scripts read from there. Bundle order matters: `shared/text_utils` →
`shared/selectors` → `recorder/inject` so each consumer's globals exist
before it runs.

## Adding a new script

1. Drop a new `.js` file under the appropriate subdirectory.
2. Wrap it in the standard IIFE + `window.__rpa<Name>Loaded` guard.
3. Add a unit test in `tests/test_page_scripts.py` asserting `load("dir/name")`
   returns the expected starting bytes.
4. If it's a new shared utility, namespace it under `window.__rpa.shared.<name>`.
