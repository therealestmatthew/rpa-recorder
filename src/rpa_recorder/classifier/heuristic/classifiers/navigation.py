"""Classify NAVIGATE actions as NAVIGATION (the rule is logically equivalent)."""

from rpa_recorder.models import ActionType, RecordedAction, SemanticIntent

from ..protocol import ClassifyCandidate, RuleContext


class NavigationClassifier:
    """`action_type == NAVIGATE` is itself the signal — confidence 1.00 is appropriate."""

    name: str = "navigation"

    def apply(self, action: RecordedAction, ctx: RuleContext) -> ClassifyCandidate | None:  # noqa: ARG002
        if action.action_type is not ActionType.NAVIGATE:
            return None
        return ClassifyCandidate(
            intent=SemanticIntent.NAVIGATION,
            confidence=1.00,
            reasoning="navigate action",
            source=self.name,
        )
