"""Shared helpers for `PromptStrategy` implementations.

Centralises three concerns that every classification prompt needs:
- redaction of `is_sensitive=True` payloads (the trust boundary — passwords
  must never reach the API),
- truncation of long payload values (defence against pathological pages),
- stable signature construction for cache keys (volatile fields excluded).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from rpa_recorder.models import REDACTED_VALUE, ActionType, RecordedAction

MAX_PAYLOAD_VALUE_CHARS: int = 200


def redact_payload(action: RecordedAction) -> dict[str, Any]:
    """Return a JSON-safe payload dict with sensitive fields redacted."""
    payload = action.payload
    if hasattr(payload, "model_dump"):
        # Use the InputPayload serializer's `redact_secrets` context hook.
        data = payload.model_dump(context={"redact_secrets": True})
    else:
        data = dict(payload)
        if data.get("is_sensitive") and "value" in data:
            data["value"] = REDACTED_VALUE
    if isinstance(data.get("value"), str) and len(data["value"]) > MAX_PAYLOAD_VALUE_CHARS:
        data["value"] = data["value"][:MAX_PAYLOAD_VALUE_CHARS] + "…"
    return data


def selector_summary(action: RecordedAction) -> dict[str, Any]:
    """Short-string-only projection of the selector for prompts."""
    sel = action.selector
    if sel is None:
        return {}
    return {
        k: v
        for k, v in sel.model_dump().items()
        if v is not None and not (isinstance(v, str) and not v.strip())
    }


def element_summary(action: RecordedAction) -> dict[str, Any]:
    """Per-action element snapshot trimmed to what classifiers need."""
    ctx = action.element_context
    if ctx is None:
        return {}
    return {
        "tag": ctx.tag,
        "attributes": dict(ctx.attributes),
        "visible_text": ctx.visible_text,
        "is_visible": ctx.is_visible,
        "is_enabled": ctx.is_enabled,
        "parent_form_id": ctx.parent_form_id,
        "nearby_labels": list(ctx.nearby_labels),
    }


def surrounding_summary(surrounding: list[RecordedAction]) -> list[dict[str, Any]]:
    """Compact `[type, url]` per neighbour. Used for context, not classification."""
    return [{"action_type": ActionType(a.action_type).value, "url": a.url} for a in surrounding]


def build_signature(
    *,
    action: RecordedAction,
    surrounding: list[RecordedAction],
    extra: dict[str, Any] | None = None,
) -> str:
    """Stable sha256 hex over the volatile-field-free shape of one classification."""
    payload = redact_payload(action)
    shape = {
        "action_type": ActionType(action.action_type).value,
        "url": action.url,
        "selector": selector_summary(action),
        "payload": payload,
        "element_context": element_summary(action),
        "surrounding_count": len(surrounding),
        "surrounding_types": [ActionType(a.action_type).value for a in surrounding],
        "extra": extra or {},
    }
    encoded = json.dumps(shape, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "MAX_PAYLOAD_VALUE_CHARS",
    "build_signature",
    "element_summary",
    "redact_payload",
    "selector_summary",
    "surrounding_summary",
]
