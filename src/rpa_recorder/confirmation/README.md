# confirmation

Interactive review-before-replay loop (M11). Three-axis pipeline — filters
narrow the candidate set, modes choose how to ask the operator, renderers
shape what the operator sees. Confirmed labels flow into the gold training
data on the next medallion promotion.

## Layout

```
confirmation/
├── __init__.py
├── protocol.py            # Filter / Mode / Renderer protocols
├── runner.py              # ConfirmationRunner — drives the pipeline
├── filters/               # narrow the action set
│   ├── below_threshold.py
│   ├── by_intent.py
│   ├── failed_on_replay.py
│   ├── since_date.py
│   └── unconfirmed_only.py
├── modes/                 # how to ask the operator
│   ├── per_action.py
│   ├── per_intent_batch.py
│   ├── diff_baseline.py
│   └── overview.py
└── renderers/             # what the operator sees
    ├── compact.py
    ├── detailed.py
    └── side_by_side.py
```

## Conventions

- **Confirmed labels are write-once.** Once an operator approves or
  rejects an action, the row is updated in `recorded_actions.confirmed_at`
  and an audit trail is appended. Re-running confirmation skips
  already-confirmed rows unless `--force` is passed.
- **Modes do not render.** Modes orchestrate the question-and-answer
  flow; renderers do the actual screen drawing. This keeps "ask one at a
  time" / "ask in batches" orthogonal to "compact display" / "side-by-side
  diff."
- **Confirmation triggers an immediate gold promotion.** After a session
  closes, `runner.py` enqueues `promote_silver_to_gold` so dashboards and
  the training corpus reflect the new labels without waiting for the
  cron interval.

## Adding a filter / mode / renderer

1. Pick the axis and add `confirmation/<axis>/<name>.py`.
2. Implement the corresponding protocol in `protocol.py`.
3. Register in `confirmation/<axis>/__init__.py`.
4. Wire into the CLI entry in
   [`cli/commands/confirm.py`](../cli/commands/confirm.py).
5. Add a test in `tests/test_confirmation_<axis>_<name>.py`.

## See also

- [`docs/m11-confirmation-workflow.md`](../../../docs/m11-confirmation-workflow.md) — milestone doc.
- [`medallion/README.md`](../medallion/README.md) — silver→gold promotion that consumes confirmed labels.
