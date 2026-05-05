# M2 — Data models

**Status:** completed

**Commit:** `ff5d53a feat(models): add Pydantic data models for actions, recordings, runs, and LLM calls`

**Source:** `.claude/plans/bootstrap.md` (Data Model Specification) plus the deltas decided in `.claude/plans/data-capture.md §10`.

## Goal

Every Pydantic model the runtime uses, with round-trip serialization tests. The model layer is the contract between the recorder, executor, classifier, and storage — everything else builds on it.

## What shipped

### `src/rpa_recorder/models/actions.py`

- `ActionType(StrEnum)` — CLICK, INPUT, NAVIGATE, SELECT, HOVER, KEY_PRESS, SCROLL, WAIT, ASSERT, UPLOAD.
- `SemanticIntent(StrEnum)` — LOGIN, SEARCH, FORM_FILL, FORM_SUBMIT, NAVIGATION, DATA_EXTRACTION, CONFIRMATION, DISMISS_MODAL, SELECTION, UNKNOWN.
- `ElementSelector` — `role`, `accessible_name`, `test_id`, `text_content`, `css`, `xpath`, `nth`.
- `ElementContext` — `tag`, `attributes`, `visible_text`, `bounding_box`, `is_visible`, `is_enabled`, `parent_form_id`, `nearby_labels`.
- `ClickPayload`, `InputPayload`, `NavigatePayload`, `SelectPayload`. `InputPayload` carries `value`, `is_sensitive`, `clear_first`.
- `ActionPayload = ClickPayload | InputPayload | NavigatePayload | SelectPayload | dict[str, Any]`.
- `RecordedAction` — id (UUID), sequence, timestamp, action_type, payload, selector, element_context, url, page_title, **frame_url** (delta vs spec), viewport, semantic_intent, classification_confidence, classification_reasoning, user_confirmed, user_label, is_parameterized, parameter_name.
- `REDACTED_VALUE = "***REDACTED***"`.

### Sensitive-value redaction

`InputPayload` defines a `model_serializer(mode="wrap")` that inspects `info.context`. When `model_dump(context={"redact_secrets": True})` is called and `is_sensitive=True`, `value` is replaced with `***REDACTED***`. Pydantic propagates the context through nested serializations, so a `RecordedAction.model_dump(context={"redact_secrets": True})` redacts the password too.

### `src/rpa_recorder/models/recording.py`

- `ParameterDef` — `name`, `type` (literal), `default`, `description`.
- `NetworkEvent` — timestamp, method, url, status, request_headers, response_summary.
- `Recording` — id, name, description, created_at, created_by, starting_url, actions, network_log, parameters, tags.

### `src/rpa_recorder/models/execution.py`

- `ExecutionStatus(StrEnum)` — PENDING, RUNNING, SUCCESS, FAILED, RECOVERED, SKIPPED, AWAITING_CONFIRMATION.
- `FailureMode(StrEnum)` — ELEMENT_NOT_FOUND, ELEMENT_NOT_INTERACTABLE, UNEXPECTED_MODAL, NAVIGATION_FAILED, VALIDATION_ERROR, TIMEOUT, NETWORK_ERROR, UNKNOWN.
- `ExecutionAttempt` — attempt_number, started_at, ended_at, status, selector_used, failure_mode, error_message, screenshot_path, dom_snapshot_path, **accessibility_snapshot_path** (delta), **console_log** (delta), **js_errors** (delta).
- `RecoveryAction` — strategy, rationale, succeeded, new_selector.
- `ActionExecution` — action_id, status, attempts, recovery, duration_ms.
- `RunResult` — id, recording_id, started_at, ended_at, status, parameter_values, executions, summary.

### `src/rpa_recorder/models/llm.py`

`LLMCall` — id, called_for (`classify`|`recover`), model, prompt, response, recording_id?, run_id?, action_id?, input_tokens?, output_tokens?, latency_ms, created_at, error?.

### Re-exports

`src/rpa_recorder/models/__init__.py` alphabetizes the full surface in `__all__`.

## Tests

`tests/test_models.py` — 39 tests:
- Enum round-trips for every `StrEnum`.
- Selector / context construction.
- Payload validation and defaults.
- Redaction (including propagation through `Recording` and `RecordedAction`).
- `RecordedAction` round-trips for each payload type.
- `RunResult` with recovery, `LLMCall`, `ParameterDef` parametrized.

`tests/test_smoke.py` — package import test.

## Critical files

- `src/rpa_recorder/models/actions.py`
- `src/rpa_recorder/models/recording.py`
- `src/rpa_recorder/models/execution.py`
- `src/rpa_recorder/models/llm.py`
- `src/rpa_recorder/models/__init__.py`
- `tests/test_models.py`
