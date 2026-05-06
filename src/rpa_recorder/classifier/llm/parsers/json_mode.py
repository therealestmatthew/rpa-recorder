"""Fallback parser: parse JSON from `response.text`.

Used by prompts that ask the model for `{"intent": "...", "confidence": ...,
"reasoning": "..."}` instead of invoking a tool. Malformed JSON returns
None and logs — the orchestrator treats that as an abstention.
"""

from __future__ import annotations

import json
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


class JsonModeParser:
    """Parse JSON object from the response text."""

    name: str = "json_mode"

    def parse(self, response: LLMResponse) -> ClassifyCandidate | None:
        text = (response.text or "").strip()
        if not text:
            return None
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            _log.warning("llm_json_mode_parse_failed", error=str(exc))
            return None
        if not isinstance(data, dict):
            return None
        intent = _coerce_intent(data.get("intent"))
        if intent is None:
            return None
        try:
            confidence = float(data.get("confidence", 0.0))
        except TypeError, ValueError:
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))
        reasoning = str(data.get("reasoning", "")).strip() or "no reasoning"
        return ClassifyCandidate(
            intent=intent,
            confidence=confidence,
            reasoning=reasoning,
            source="llm",
        )


__all__ = ["JsonModeParser"]
