# recovery

Modular recovery pipeline (M10). When the executor can't resolve a selector
or an action fails, the recovery engine runs strategies in priority order
until one succeeds or all are exhausted. The corrected `ElementSelector`
flows back into the action result and (via M11.5) into the
`gold_replay_scripts` Parquet so future replays self-heal.

## Layout

```
recovery/
├── __init__.py
├── protocol.py                # Strategy + Verifier protocols
├── engine.py                  # RecoveryEngine — orchestrates strategy pipeline
├── strategies/
│   ├── wait_and_retry.py      # transient failures
│   ├── scroll_into_view.py    # element exists but not visible
│   ├── dismiss_modal.py       # unexpected modal blocks click
│   ├── frame_switch.py        # element is in an iframe
│   └── llm_reselect.py        # last resort: LLM proposes a new selector
├── prompts/
│   └── reselect_v1.py         # prompt for llm_reselect
└── parsers/
    └── selector_tool_use.py   # parse the LLM's tool-use response
```

## Conventions

- **Strategies run in priority order.** `wait_and_retry` is cheapest
  (no LLM call); `llm_reselect` is most expensive (an Anthropic round
  trip). The engine short-circuits on first success.
- **Recursion is bounded.** `Config.recovery_max_depth` (default 1)
  prevents a recovered action from triggering another recovery if it
  also fails. Without this, drift cascades.
- **The verifier is mandatory.** After any strategy modifies the action
  (e.g., `llm_reselect` proposes a new selector), the verifier confirms
  the new state actually works before committing. Failed verification
  → next strategy.
- **`llm_reselect` writes its prompt and response to bronze.** Same
  pattern as [`classifier/llm/`](../classifier/) — every model call gets
  an audit row in `llm_calls` plus a JSON blob under
  `data/bronze/llm/<call-id>.json`. `is_sensitive=True` payloads are
  redacted from the prompt.

## Adding a strategy

1. Add `recovery/strategies/<name>.py` implementing the `Strategy`
   protocol.
2. Register in `recovery/strategies/__init__.py` with a priority
   (lower = earlier in the pipeline).
3. If the strategy modifies the selector, write a verifier hook so the
   engine confirms the change works before committing.
4. Add a test in `tests/test_recovery_<name>.py`.

## See also

- [`docs/m10-recovery-engine.md`](../../../docs/m10-recovery-engine.md) — milestone doc.
- [`classifier/README.md`](../classifier/README.md) — the LLM tier `llm_reselect` reuses.
- [`browser/README.md`](../browser/README.md) — executor that triggers recovery on failure.
