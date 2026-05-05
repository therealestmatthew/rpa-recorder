"""Classify search-shaped INPUT actions as SEARCH."""

from rpa_recorder.models import ActionType, RecordedAction, SemanticIntent

from ..protocol import ClassifyCandidate, RuleContext


class SearchClassifier:
    """Fires on `role="searchbox"`, `type="search"`, or "search" in placeholder/name/aria-label."""

    name: str = "search"

    def apply(self, action: RecordedAction, ctx: RuleContext) -> ClassifyCandidate | None:  # noqa: ARG002
        if action.action_type is not ActionType.INPUT:
            return None
        attrs = action.element_context.attributes if action.element_context else {}
        role = action.selector.role if action.selector else None
        if role == "searchbox":
            return self._verdict("role=searchbox")
        if attrs.get("type") == "search":
            return self._verdict("type=search")
        haystack_parts = [
            attrs.get("placeholder", ""),
            attrs.get("name", ""),
            attrs.get("aria-label", ""),
        ]
        haystack = " ".join(haystack_parts).lower()
        if "search" in haystack:
            return self._verdict("'search' in placeholder/name/aria-label")
        return None

    def _verdict(self, reasoning: str) -> ClassifyCandidate:
        return ClassifyCandidate(
            intent=SemanticIntent.SEARCH,
            confidence=0.90,
            reasoning=reasoning,
            source=self.name,
        )
