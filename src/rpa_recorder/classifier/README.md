# classifier

Two-tier intent classifier (M7 + M9). Heuristic rules run first; below a
configurable confidence threshold the action escalates to an LLM. Result is
a `SemanticIntent` attached to each `RecordedAction`.

## Layout

```
classifier/
├── __init__.py
├── heuristic/                       # M7 — pure-Python pipeline
│   ├── protocol.py                  # Filter / Normalizer / Classifier protocols
│   ├── engine.py                    # orchestrates filter → normalize → classify
│   ├── filters/                     # drop noise events
│   │   ├── drop_coalesced_followers.py
│   │   ├── drop_disabled_target.py
│   │   ├── drop_duplicate_navigate.py
│   │   └── drop_focus_blur_only.py
│   ├── normalizers/                 # rewrite events to canonical shape
│   │   ├── canonicalize_url.py
│   │   ├── coalesce_input_bursts.py
│   │   └── trim_input_value.py
│   └── classifiers/                 # assign SemanticIntent
│       ├── confirmation.py
│       ├── dismiss_modal.py
│       ├── form_fill.py
│       ├── form_submit.py
│       ├── login.py
│       ├── navigation.py
│       └── search.py
└── llm/                             # M9 — pluggable LLM tier
    ├── protocol.py                  # LLMBackend / Prompt / Parser protocols
    ├── classifier.py                # LLMClassifier (orchestrator)
    ├── hybrid.py                    # HybridClassifier (heuristic → LLM escalation)
    ├── concurrency.py               # asyncio.Semaphore cap
    ├── retry.py                     # RetryPolicy (exponential backoff)
    ├── cache.py                     # response cache keyed on prompt hash
    ├── cost.py                      # per-call USD accounting → daily budget guard
    ├── merge.py                     # heuristic + LLM result merge strategies
    ├── backends/
    │   └── anthropic.py             # AnthropicBackend (claude-* models)
    ├── prompts/
    │   ├── base.py
    │   └── classify_v1.py
    └── parsers/
        ├── free_form.py
        ├── json_mode.py
        └── tool_use.py
```

## Conventions

- **Protocol-based extension.** Three axes in `heuristic/`
  (filter, normalizer, classifier) and three in `llm/` (backend,
  prompt, parser). Each is a `Protocol` in its layer's `protocol.py`.
  Adding a rule = adding a module + registering it in the `__init__.py`.
- **Heuristic first, LLM only when needed.** `HybridClassifier` runs the
  heuristic pipeline; if `result.confidence < Config.classifier_confidence_threshold`
  (default `0.7`), it escalates to the LLM tier. Direct LLM-only use is
  still supported for evaluation.
- **`is_sensitive=True` payloads are redacted before LLM prompts.**
  `prompts/base.py` enforces this — no exceptions. The corresponding
  bronze JSON blob preserves the raw value (bronze is operator-private).
- **LLM concurrency is per-classifier-instance.** Each `LLMClassifier`
  owns an `asyncio.Semaphore(Config.llm_max_concurrency)` (default 5).
  Multiple workers running in parallel multiply this — total concurrency
  is `worker_count × llm_max_concurrency`.
- **The Anthropic SDK's own retries are disabled.** `AnthropicBackend`
  passes `max_retries=0`; `RetryPolicy` is the sole retry layer so we
  count attempts, log them, and respect the daily budget guard.
- **Daily budget guard is real.** `cost.py` accumulates per-call USD;
  `LLMBudgetExceeded` is raised when `Config.llm_daily_budget_usd` is
  hit. The guard does not roll over silently.

## Adding a heuristic rule

1. Pick the right axis: filter (drops events), normalizer (rewrites
   events), or classifier (assigns `SemanticIntent`).
2. Add `heuristic/<axis>/<name>.py` implementing the protocol.
3. Register in `heuristic/<axis>/__init__.py`.
4. Add a test in `tests/test_heuristic_<axis>_<name>.py`.

## Adding an LLM backend / prompt / parser

1. Pick the axis and add a module under `llm/<axis>/<name>.py`.
2. Implement the protocol in `llm/protocol.py`.
3. Wire into the `HybridClassifier` factory.
4. Add a test under `tests/test_llm_<axis>_<name>.py` using `respx` (HTTP)
   or a fake `LLMBackend` instance — don't hit the real API in unit tests.

## See also

- [`docs/m7-heuristic-classifier.md`](../../../docs/m7-heuristic-classifier.md) — heuristic milestone.
- [`docs/m9-llm-classifier.md`](../../../docs/m9-llm-classifier.md) — LLM milestone.
- [`models/README.md`](../models/README.md) — `SemanticIntent` and related types.
