"""`reselect_v1` — tool-use prompt for picking a fresh `ElementSelector`.

One user message containing the failed action's selector + context + a
filtered DOM (≤5 KB, scripts/styles/svg/comments stripped) and a `reselect`
tool whose schema mirrors `ElementSelector`. Tool use gives schema-validated
output so the parser logic stays trivial.

Bumping `version` here invalidates every cached entry naturally — callers
never have to manually flush.
"""

import hashlib
import json
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from rpa_recorder.models import FailureMode, RecordedAction


_SYSTEM = (
    "You re-pick a CSS / XPath / role-based selector for a recorded browser action "
    "whose original selector no longer resolves. Use the failure mode and the "
    "filtered DOM to find the most likely current target. Always respond by "
    "invoking the `reselect` tool. If the page does not contain a plausible "
    "target, return an empty selector (all fields null)."
)


def _redacted_payload(action: RecordedAction) -> dict[str, Any]:
    dumped: dict[str, Any] = action.model_dump(mode="json", context={"redact_secrets": True})
    payload = dumped.get("payload", {})
    return payload if isinstance(payload, dict) else {}


def _selector_summary(action: RecordedAction) -> dict[str, Any]:
    if action.selector is None:
        return {}
    return action.selector.model_dump(exclude_none=True)


class ReselectV1Prompt:
    """Tool-use prompt: failed action + filtered DOM → fresh `ElementSelector`."""

    name: str = "reselect_v1"
    version: str = "1"

    _TOOL: ClassVar[dict[str, Any]] = {
        "name": "reselect",
        "description": "Record a fresh element selector for the failed action.",
        "input_schema": {
            "type": "object",
            "properties": {
                "test_id": {"type": ["string", "null"], "description": "data-testid value"},
                "role": {"type": ["string", "null"], "description": "ARIA role"},
                "accessible_name": {
                    "type": ["string", "null"],
                    "description": "Accessible name (matches role)",
                },
                "text_content": {
                    "type": ["string", "null"],
                    "description": "Exact visible text",
                },
                "css": {"type": ["string", "null"], "description": "CSS selector"},
                "xpath": {"type": ["string", "null"], "description": "XPath expression"},
                "rationale": {
                    "type": "string",
                    "description": "Short justification — one or two sentences.",
                },
            },
            "required": ["rationale"],
        },
    }

    def build(
        self,
        action: RecordedAction,
        filtered_dom: str,
        failure_mode: FailureMode,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]] | None]:
        """Construct the messages + tools for one reselection call."""
        body = {
            "system_summary": _SYSTEM,
            "failure_mode": failure_mode.value,
            "failed_action": {
                "action_type": action.action_type.value,
                "url": action.url,
                "page_title": action.page_title,
                "frame_url": action.frame_url,
                "original_selector": _selector_summary(action),
                "payload": _redacted_payload(action),
            },
            "filtered_dom": filtered_dom,
        }
        messages: list[dict[str, Any]] = [
            {
                "role": "user",
                "content": (
                    "The selector below no longer resolves. Use the `reselect` tool "
                    "to pick the most likely current target from the filtered DOM. "
                    "Prefer test_id > role+name > text_content > css > xpath.\n\n"
                    f"```json\n{json.dumps(body, indent=2, default=str, ensure_ascii=False)}\n```"
                ),
            }
        ]
        return messages, [self._TOOL]

    def signature(
        self,
        action: RecordedAction,
        filtered_dom: str,
        failure_mode: FailureMode,
    ) -> str:
        """Stable cache key seed; excludes timestamps + UUIDs."""
        seed = json.dumps(
            {
                "prompt": self.name,
                "version": self.version,
                "action_type": action.action_type.value,
                "url": action.url,
                "frame_url": action.frame_url,
                "original_selector": _selector_summary(action),
                "failure_mode": failure_mode.value,
                "dom_sha256": hashlib.sha256(filtered_dom.encode("utf-8")).hexdigest(),
            },
            sort_keys=True,
        )
        return hashlib.sha256(seed.encode("utf-8")).hexdigest()


__all__ = ["ReselectV1Prompt"]
