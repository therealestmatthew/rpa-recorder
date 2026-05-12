# models

Pydantic v2 domain models (M2). One module per concern. These are the
shapes that flow between layers; SQLAlchemy table definitions live in
[`storage/`](../storage/) and are mapped to/from these models via
repositories.

## Layout

```
models/
├── __init__.py
├── actions.py     # RecordedAction + ElementSelector + SemanticIntent
├── recording.py   # Recording, NetworkEvent, BronzeArtifact pointer
├── execution.py   # RunResult, ActionExecution, ExecutionAttempt, RecoveryAction
└── llm.py         # LLMCall — prompt/response audit row
```

## Conventions

- **Pydantic v2 with strict mode.** Model configs use
  `ConfigDict(strict=True, frozen=True)` where the model is read-only
  after construction (most are). The `pydantic.mypy` plugin enforces
  this at type-check time.
- **`from __future__ import annotations` is not used.** This project
  follows runtime-eager imports; type-only imports go under
  `if TYPE_CHECKING:`. See [`CLAUDE.md`](../../../CLAUDE.md).
- **`is_sensitive` is a field, not a convention.** Any model carrying
  user-entered data exposes an `is_sensitive: bool` flag. Downstream
  layers (LLM prompts, API responses, CLI rendering) read this and
  redact accordingly.

## See also

- [`docs/_archive/m2-data-models.md`](../../../docs/_archive/m2-data-models.md) — milestone doc with full schema rationale.
- [`docs/glossary.md`](../../../docs/glossary.md) — term definitions for `Action`, `Recording`, `RunResult`, etc.
- [`storage/README.md`](../storage/README.md) — SQLAlchemy tables that mirror these models.
