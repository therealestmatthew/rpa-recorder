"""Classify INPUT actions on `type=password` fields as LOGIN."""

from rpa_recorder.models import ActionType, RecordedAction, SemanticIntent

from ..protocol import ClassifyCandidate, RuleContext


class LoginClassifier:
    """High-confidence: input on `type="password"` is unambiguously a login field."""

    name: str = "login"

    def apply(self, action: RecordedAction, ctx: RuleContext) -> ClassifyCandidate | None:  # noqa: ARG002
        if action.action_type is not ActionType.INPUT:
            return None
        attrs = action.element_context.attributes if action.element_context else {}
        if attrs.get("type") == "password":
            return ClassifyCandidate(
                intent=SemanticIntent.LOGIN,
                confidence=0.95,
                reasoning="password field",
                source=self.name,
            )
        return None
