"""Tests for the three-pipeline heuristic engine.

Covers ordering, tie-breaking, abstention, drop logging via structlog,
custom-pipeline construction, default-pipeline smoke, and per-call context
isolation.
"""

from typing import TYPE_CHECKING

import structlog.testing

from rpa_recorder.classifier.heuristic import (
    ClassifyCandidate,
    ClassifyPipeline,
    FilterPipeline,
    HeuristicEngine,
    NormalizePipeline,
    RuleContext,
    default_pipeline,
)
from rpa_recorder.models import (
    ActionType,
    ClickPayload,
    ElementContext,
    ElementSelector,
    InputPayload,
    NavigatePayload,
    RecordedAction,
    SemanticIntent,
)

if TYPE_CHECKING:
    from collections.abc import Callable


class _FixedClassifyRule:
    """Test helper: always returns a fixed candidate."""

    def __init__(self, intent: SemanticIntent, confidence: float, name: str = "fixed") -> None:
        self.intent = intent
        self.confidence = confidence
        self.name = name

    def apply(self, action: RecordedAction, ctx: RuleContext) -> ClassifyCandidate | None:
        return ClassifyCandidate(
            intent=self.intent,
            confidence=self.confidence,
            reasoning=f"{self.name} reason",
            source=self.name,
        )


class _AbstainClassifyRule:
    """Test helper: always abstains."""

    name: str = "abstain"

    def apply(self, action: RecordedAction, ctx: RuleContext) -> ClassifyCandidate | None:
        return None


class TestPipelineOrdering:
    def test_engine_runs_pipelines_in_order_filter_normalize_classify(
        self, make_action: Callable[..., RecordedAction]
    ) -> None:
        # Action 0: focus-only INPUT (empty value, no follow-up) → filter drops.
        # Action 1: INPUT with whitespace-padded value → normalize trims.
        # Action 2: CLICK with submit text inside a form → classify picks FORM_SUBMIT.
        focus_input = make_action(
            sequence=0,
            action_type=ActionType.INPUT,
            payload=InputPayload(value=""),
            selector=ElementSelector(test_id="email"),
            element_context=ElementContext(tag="input"),
        )
        padded_input = make_action(
            sequence=1,
            offset_ms=10_000,
            action_type=ActionType.INPUT,
            payload=InputPayload(value="  alice  "),
            selector=ElementSelector(test_id="name"),
            element_context=ElementContext(tag="input"),
        )
        submit_click = make_action(
            sequence=2,
            offset_ms=20_000,
            action_type=ActionType.CLICK,
            payload=ClickPayload(),
            selector=ElementSelector(role="button", accessible_name="Submit"),
            element_context=ElementContext(tag="button", parent_form_id="loginForm"),
        )
        engine = default_pipeline()
        results = engine.process([focus_input, padded_input, submit_click])
        assert len(results) == 2
        normalized_input, _ = results[0]
        assert isinstance(normalized_input.payload, InputPayload)
        assert normalized_input.payload.value == "alice"
        _, click_verdict = results[1]
        assert click_verdict.intent is SemanticIntent.FORM_SUBMIT


class TestClassifySelection:
    def test_classify_picks_highest_confidence_candidate(
        self, make_action: Callable[..., RecordedAction]
    ) -> None:
        action = make_action(sequence=0)
        ctx = RuleContext(actions=[action], index=0)
        pipeline = ClassifyPipeline(
            [
                _FixedClassifyRule(SemanticIntent.LOGIN, 0.5, name="low"),
                _FixedClassifyRule(SemanticIntent.SEARCH, 0.9, name="high"),
            ]
        )
        verdict = pipeline.apply(action, ctx)
        assert verdict.intent is SemanticIntent.SEARCH
        assert verdict.confidence == 0.9
        assert verdict.source == "high"

    def test_classify_breaks_ties_by_registration_order(
        self, make_action: Callable[..., RecordedAction]
    ) -> None:
        action = make_action(sequence=0)
        ctx = RuleContext(actions=[action], index=0)
        pipeline = ClassifyPipeline(
            [
                _FixedClassifyRule(SemanticIntent.LOGIN, 0.7, name="first"),
                _FixedClassifyRule(SemanticIntent.SEARCH, 0.7, name="second"),
            ]
        )
        verdict = pipeline.apply(action, ctx)
        assert verdict.source == "first"
        assert verdict.intent is SemanticIntent.LOGIN

    def test_classify_returns_unknown_when_no_rule_matches(
        self, make_action: Callable[..., RecordedAction]
    ) -> None:
        action = make_action(sequence=0)
        ctx = RuleContext(actions=[action], index=0)
        pipeline = ClassifyPipeline([_AbstainClassifyRule()])
        verdict = pipeline.apply(action, ctx)
        assert verdict.intent is SemanticIntent.UNKNOWN
        assert verdict.confidence == 0.0
        assert verdict.reasoning == "no rule matched"
        assert verdict.source == "default"


class TestEngineLogging:
    def test_engine_logs_dropped_actions_with_rule_name(
        self, make_action: Callable[..., RecordedAction]
    ) -> None:
        disabled_click = make_action(
            sequence=7,
            action_type=ActionType.CLICK,
            element_context=ElementContext(tag="button", is_enabled=False),
        )
        engine = default_pipeline()
        with structlog.testing.capture_logs() as captured:
            results = engine.process([disabled_click])
        assert results == []
        drops = [r for r in captured if r.get("event") == "action_dropped"]
        assert len(drops) >= 1
        first_drop = drops[0]
        assert first_drop["rule_name"] == "drop_disabled_target"
        assert first_drop["sequence"] == 7
        assert "reason" in first_drop


class TestEngineConstruction:
    def test_engine_supports_custom_pipeline(
        self, make_action: Callable[..., RecordedAction]
    ) -> None:
        engine = HeuristicEngine(
            filter_pipeline=FilterPipeline([]),
            normalize_pipeline=NormalizePipeline([]),
            classify_pipeline=ClassifyPipeline([]),
        )
        action = make_action(sequence=0)
        results = engine.process([action])
        assert len(results) == 1
        assert results[0][0] is action
        assert results[0][1].intent is SemanticIntent.UNKNOWN
        assert results[0][1].source == "default"

    def test_default_pipeline_smoke(self, make_action: Callable[..., RecordedAction]) -> None:
        actions = [
            make_action(
                sequence=0,
                action_type=ActionType.NAVIGATE,
                payload=NavigatePayload(url="https://example.com/login"),
            ),
            make_action(
                sequence=1,
                offset_ms=10_000,
                action_type=ActionType.INPUT,
                payload=InputPayload(value="alice@example.com"),
                selector=ElementSelector(test_id="email"),
                element_context=ElementContext(tag="input", attributes={"type": "email"}),
            ),
            make_action(
                sequence=2,
                offset_ms=20_000,
                action_type=ActionType.INPUT,
                payload=InputPayload(value="hunter2", is_sensitive=True),
                selector=ElementSelector(test_id="password"),
                element_context=ElementContext(tag="input", attributes={"type": "password"}),
            ),
            make_action(
                sequence=3,
                offset_ms=30_000,
                action_type=ActionType.CLICK,
                selector=ElementSelector(role="button", accessible_name="Submit"),
                element_context=ElementContext(tag="button", parent_form_id="loginForm"),
            ),
            make_action(
                sequence=4,
                offset_ms=40_000,
                action_type=ActionType.NAVIGATE,
                payload=NavigatePayload(url="https://example.com/home"),
            ),
        ]
        engine = default_pipeline()
        results = engine.process(actions)
        assert len(results) == 5
        intents = [v.intent for _, v in results]
        assert SemanticIntent.NAVIGATION in intents
        assert SemanticIntent.LOGIN in intents
        assert SemanticIntent.FORM_SUBMIT in intents

    def test_engine_constructs_fresh_context_per_process_call(
        self, make_action: Callable[..., RecordedAction]
    ) -> None:
        # Coalesce burst: 3 INPUTs on the same selector at 0/50/100ms.
        # With fresh context per call, both runs collapse to one carrier
        # action with value "ali". If scratch leaked, the second run's
        # pre-normalize filter would drop sequences 1 and 2 *before*
        # the normalizer can update the leader, leaving the leader's
        # value as "a".
        actions = [
            make_action(
                sequence=0,
                action_type=ActionType.INPUT,
                payload=InputPayload(value="a"),
                selector=ElementSelector(test_id="email"),
                element_context=ElementContext(tag="input"),
            ),
            make_action(
                sequence=1,
                offset_ms=50,
                action_type=ActionType.INPUT,
                payload=InputPayload(value="al"),
                selector=ElementSelector(test_id="email"),
                element_context=ElementContext(tag="input"),
            ),
            make_action(
                sequence=2,
                offset_ms=100,
                action_type=ActionType.INPUT,
                payload=InputPayload(value="ali"),
                selector=ElementSelector(test_id="email"),
                element_context=ElementContext(tag="input"),
            ),
        ]
        engine = default_pipeline()
        first = engine.process(actions)
        second = engine.process(actions)
        assert len(first) == 1
        assert len(second) == 1
        first_action, _ = first[0]
        second_action, _ = second[0]
        assert isinstance(first_action.payload, InputPayload)
        assert isinstance(second_action.payload, InputPayload)
        assert first_action.payload.value == "ali"
        assert second_action.payload.value == "ali"
