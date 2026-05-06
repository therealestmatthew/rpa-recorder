"""Last-resort parser: regex over free-form `INTENT: <value>` text.

Useful for very small or older models that struggle with both tool use and
JSON mode. Default confidence is 0.5 because the model couldn't produce a
structured signal — caller should treat that as low-trust.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from rpa_recorder.classifier.heuristic.protocol import ClassifyCandidate
from rpa_recorder.models import SemanticIntent

if TYPE_CHECKING:
    from ..protocol import LLMResponse

_INTENT_RE = re.compile(r"\bintent\s*[:=]\s*([a-z_]+)", re.IGNORECASE)
_CONF_RE = re.compile(r"\bconfidence\s*[:=]\s*([01]?\.\d+|[01](?!\d))", re.IGNORECASE)
_REASON_RE = re.compile(r"\breasoning\s*[:=]\s*(.+?)(?:\n|$)", re.IGNORECASE)


class FreeFormParser:
    """Pull intent/confidence/reasoning from raw text via regex."""

    name: str = "free_form"

    def parse(self, response: LLMResponse) -> ClassifyCandidate | None:
        text = response.text or ""
        intent_match = _INTENT_RE.search(text)
        if intent_match is None:
            return None
        try:
            intent = SemanticIntent(intent_match.group(1).lower())
        except ValueError:
            return None
        conf_match = _CONF_RE.search(text)
        confidence = float(conf_match.group(1)) if conf_match else 0.5
        confidence = max(0.0, min(1.0, confidence))
        reason_match = _REASON_RE.search(text)
        reasoning = reason_match.group(1).strip() if reason_match else "free-form parse"
        return ClassifyCandidate(
            intent=intent,
            confidence=confidence,
            reasoning=reasoning,
            source="llm",
        )


__all__ = ["FreeFormParser"]
