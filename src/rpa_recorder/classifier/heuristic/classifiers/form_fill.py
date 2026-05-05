"""Catch-all classifier: any INPUT not claimed by a higher-confidence rule is FORM_FILL."""

from rpa_recorder.models import ActionType, RecordedAction, SemanticIntent

from ..protocol import ClassifyCandidate, RuleContext


class FormFillClassifier:
    """Catch-all for INPUT actions; shadowed by LOGIN (0.95) and SEARCH (0.90)."""

    name: str = "form_fill"

    def apply(self, action: RecordedAction, ctx: RuleContext) -> ClassifyCandidate | None:  # noqa: ARG002
        if action.action_type is not ActionType.INPUT:
            return None
        return ClassifyCandidate(
            intent=SemanticIntent.FORM_FILL,
            confidence=0.70,
            reasoning="generic input field",
            source=self.name,
        )
