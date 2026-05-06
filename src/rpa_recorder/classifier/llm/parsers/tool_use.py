"""Default parser: pull the first `classify` tool_use block.

Tool use is preferred over JSON-in-text for newer Sonnet models because the
SDK validates the input schema before handing the call back. If no `classify`
tool block is present, returns None and the orchestrator falls through to
UNKNOWN (the audit row is still written).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from rpa_recorder.classifier.heuristic.protocol import ClassifyCandidate
from rpa_recorder.models import SemanticIntent

if TYPE_CHECKING:
    from ..protocol import LLMResponse

_log = structlog.get_logger(__name__)


def _coerce_intent(value: object) -> SemanticIntent | None:
    if isinstance(value, SemanticIntent):
        return value
    if not isinstance(value, str):
        return None
    try:
        return SemanticIntent(value)
    except ValueError:
        return None


class ToolUseParser:
    """Find the first tool_use named `classify` and return a candidate."""

    name: str = "tool_use"

    def parse(self, response: LLMResponse) -> ClassifyCandidate | None:
        for call in response.tool_calls:
            if call.get("name") != "classify":
                continue
            args = call.get("input", {})
            intent = _coerce_intent(args.get("intent"))
            if intent is None:
                _log.warning("llm_tool_use_invalid_intent", got=args.get("intent"))
                return None
            try:
                confidence = float(args.get("confidence", 0.0))
            except TypeError, ValueError:
                confidence = 0.0
            confidence = max(0.0, min(1.0, confidence))
            reasoning = str(args.get("reasoning", "")).strip() or "no reasoning"
            return ClassifyCandidate(
                intent=intent,
                confidence=confidence,
                reasoning=reasoning,
                source="llm",
            )
        return None


__all__ = ["ToolUseParser"]
