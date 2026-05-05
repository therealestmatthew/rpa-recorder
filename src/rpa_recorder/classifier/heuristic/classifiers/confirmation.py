"""Classify CLICKs with confirmation-shaped text as CONFIRMATION."""

import re

from rpa_recorder.models import ActionType, RecordedAction, SemanticIntent

from ..protocol import ClassifyCandidate, RuleContext

_CONFIRM_TEXT_RE = re.compile(r"^(ok|confirm|yes|accept)$", re.IGNORECASE)


class ConfirmationClassifier:
    """Buttons labeled OK / Confirm / Yes / Accept signal user confirmation."""

    name: str = "confirmation"

    def apply(self, action: RecordedAction, ctx: RuleContext) -> ClassifyCandidate | None:  # noqa: ARG002
        if action.action_type is not ActionType.CLICK:
            return None
        text = (action.selector.accessible_name if action.selector else None) or ""
        text = text.strip()
        if not text or not _CONFIRM_TEXT_RE.match(text):
            return None
        return ClassifyCandidate(
            intent=SemanticIntent.CONFIRMATION,
            confidence=0.80,
            reasoning=f"confirmation-shaped button '{text}'",
            source=self.name,
        )
