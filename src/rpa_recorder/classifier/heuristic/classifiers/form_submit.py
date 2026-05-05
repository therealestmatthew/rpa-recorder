"""Classify CLICKs with submit-shaped text inside a form as FORM_SUBMIT."""

import re

from rpa_recorder.models import ActionType, RecordedAction, SemanticIntent

from ..protocol import ClassifyCandidate, RuleContext

_SUBMIT_TEXT_RE = re.compile(r"^(submit|save|continue|next)$", re.IGNORECASE)


class FormSubmitClassifier:
    """Submit-shaped button text + a parent form is a strong submit signal."""

    name: str = "form_submit"

    def apply(self, action: RecordedAction, ctx: RuleContext) -> ClassifyCandidate | None:  # noqa: ARG002
        if action.action_type is not ActionType.CLICK:
            return None
        text = (action.selector.accessible_name if action.selector else None) or ""
        text = text.strip()
        if not text or not _SUBMIT_TEXT_RE.match(text):
            return None
        if action.element_context is None or action.element_context.parent_form_id is None:
            return None
        return ClassifyCandidate(
            intent=SemanticIntent.FORM_SUBMIT,
            confidence=0.85,
            reasoning=f"submit-shaped button '{text}' inside form",
            source=self.name,
        )
