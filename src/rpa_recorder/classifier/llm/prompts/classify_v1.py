"""`classify_v1` — the default tool-use prompt for action classification.

Builds a single user message from the redacted action + surrounding type
sequence and a `classify` tool whose `intent` parameter is constrained to
the `SemanticIntent` enum. Tool use gives us schema-validated output, so
the parser logic is trivial.

Bumping `version` here invalidates every cached entry naturally — never
manually flush Redis on a prompt change.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, ClassVar

from rpa_recorder.models import SemanticIntent

from .base import (
    build_signature,
    element_summary,
    redact_payload,
    selector_summary,
    surrounding_summary,
)

if TYPE_CHECKING:
    from rpa_recorder.models import RecordedAction


_INTENT_VALUES: list[str] = [intent.value for intent in SemanticIntent]


_SYSTEM = (
    "You classify a single recorded browser action with the most fitting semantic intent. "
    "Use the surrounding action types only for context — your verdict is for the focus action. "
    "Always respond by invoking the `classify` tool. Pick UNKNOWN when the signals are unclear."
)


class ClassifyV1Prompt:
    """Tool-use prompt: one user message, one constrained tool."""

    name: str = "classify_v1"
    version: str = "1"

    _TOOL: ClassVar[dict[str, Any]] = {
        "name": "classify",
        "description": "Record the semantic intent of the focus action.",
        "input_schema": {
            "type": "object",
            "properties": {
                "intent": {
                    "type": "string",
                    "enum": _INTENT_VALUES,
                    "description": "Best-fit semantic intent for the focus action.",
                },
                "confidence": {
                    "type": "number",
                    "minimum": 0.0,
                    "maximum": 1.0,
                    "description": "Self-rated confidence in the picked intent.",
                },
                "reasoning": {
                    "type": "string",
                    "description": "Short justification — one or two sentences.",
                },
            },
            "required": ["intent", "confidence", "reasoning"],
        },
    }

    def build(
        self,
        action: RecordedAction,
        surrounding: list[RecordedAction],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]] | None]:
        """Construct the messages + tools for one classification call."""
        focus = {
            "action_type": action.action_type.value,
            "url": action.url,
            "page_title": action.page_title,
            "selector": selector_summary(action),
            "payload": redact_payload(action),
            "element_context": element_summary(action),
        }
        body = {
            "system_summary": _SYSTEM,
            "focus_action": focus,
            "surrounding": surrounding_summary(surrounding),
            "allowed_intents": _INTENT_VALUES,
        }
        messages: list[dict[str, Any]] = [
            {
                "role": "user",
                "content": (
                    "Classify the focus action below. Use the `classify` tool to respond. "
                    "Surrounding actions are listed in chronological order.\n\n"
                    f"```json\n{json.dumps(body, indent=2, default=str, ensure_ascii=False)}\n```"
                ),
            }
        ]
        return messages, [self._TOOL]

    def signature(
        self,
        action: RecordedAction,
        surrounding: list[RecordedAction],
    ) -> str:
        """Cache key seed; excludes timestamps + UUIDs."""
        return build_signature(
            action=action,
            surrounding=surrounding,
            extra={"prompt": self.name, "version": self.version},
        )


__all__ = ["ClassifyV1Prompt"]
