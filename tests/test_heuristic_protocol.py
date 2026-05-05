"""Tests for the heuristic engine's protocol value types and rule context."""

from typing import TYPE_CHECKING

from rpa_recorder.classifier.heuristic import classify
from rpa_recorder.classifier.heuristic.protocol import (
    Classification,
    ClassifyCandidate,
    RuleContext,
)
from rpa_recorder.models import (
    ActionType,
    NavigatePayload,
    RecordedAction,
    SemanticIntent,
)

if TYPE_CHECKING:
    from collections.abc import Callable


class TestClassificationModels:
    def test_classification_round_trips_through_pydantic(self) -> None:
        c = Classification(
            intent=SemanticIntent.LOGIN,
            confidence=0.95,
            reasoning="password field",
            source="login",
        )
        assert Classification.model_validate(c.model_dump()) == c

    def test_classify_candidate_round_trips_through_pydantic(self) -> None:
        c = ClassifyCandidate(
            intent=SemanticIntent.SEARCH,
            confidence=0.9,
            reasoning="role=searchbox",
            source="search",
        )
        assert ClassifyCandidate.model_validate(c.model_dump()) == c


class TestRuleContext:
    def test_rule_context_scratch_is_mutable_dict(
        self, make_action: Callable[..., RecordedAction]
    ) -> None:
        ctx = RuleContext(actions=[make_action(sequence=0)], index=0)
        ctx.scratch["mark"] = {1, 2}
        assert ctx.scratch["mark"] == {1, 2}
        ctx.scratch["mark"].add(3)
        assert ctx.scratch["mark"] == {1, 2, 3}

    def test_rule_context_default_scratch_is_empty(
        self, make_action: Callable[..., RecordedAction]
    ) -> None:
        ctx = RuleContext(actions=[make_action()], index=0)
        assert ctx.scratch == {}

    def test_rule_context_index_is_required(
        self, make_action: Callable[..., RecordedAction]
    ) -> None:
        ctx = RuleContext(actions=[make_action()], index=5)
        assert ctx.index == 5


class TestClassifyConvenience:
    def test_returns_classification_for_navigate(
        self, make_action: Callable[..., RecordedAction]
    ) -> None:
        action = make_action(
            sequence=0,
            action_type=ActionType.NAVIGATE,
            payload=NavigatePayload(url="https://example.com"),
        )
        verdict = classify(action)
        assert verdict.intent is SemanticIntent.NAVIGATION
        assert verdict.confidence == 1.0
        assert verdict.source == "navigation"
