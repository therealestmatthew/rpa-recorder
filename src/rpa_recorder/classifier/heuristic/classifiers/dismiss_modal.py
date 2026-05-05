"""Classify close-icon-shaped CLICKs as DISMISS_MODAL."""

import re

from rpa_recorder.models import ActionType, RecordedAction, SemanticIntent

from ..protocol import ClassifyCandidate, RuleContext

_ARIA_LABEL_RE = re.compile(r"close|dismiss", re.IGNORECASE)
_CLOSE_TEXT_RE = re.compile(r"^(close|×|✕|x)$", re.IGNORECASE)  # noqa: RUF001


class DismissModalClassifier:
    """Fires on close-icon characters (multiplication signs), 'close' text/class, or close/dismiss aria-label."""

    name: str = "dismiss_modal"

    def apply(self, action: RecordedAction, ctx: RuleContext) -> ClassifyCandidate | None:  # noqa: ARG002
        if action.action_type is not ActionType.CLICK:
            return None
        attrs = action.element_context.attributes if action.element_context else {}
        text = ((action.selector.accessible_name if action.selector else None) or "").strip()
        aria_label = attrs.get("aria-label", "")
        css_class = attrs.get("class", "").lower()

        if aria_label and _ARIA_LABEL_RE.search(aria_label):
            return self._verdict(f"aria-label '{aria_label}' matches close/dismiss")
        if "close" in css_class:
            return self._verdict(f"class '{css_class}' contains 'close'")
        if text and _CLOSE_TEXT_RE.match(text):
            return self._verdict(f"close-icon text '{text}'")
        return None

    def _verdict(self, reasoning: str) -> ClassifyCandidate:
        return ClassifyCandidate(
            intent=SemanticIntent.DISMISS_MODAL,
            confidence=0.80,
            reasoning=reasoning,
            source=self.name,
        )
