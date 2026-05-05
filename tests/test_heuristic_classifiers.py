"""Tests for the seven default classifier rules.

Each rule has at least one positive-firing test and one abstain test;
shadowing behavior between rules is verified via the full pipeline.
"""

from typing import TYPE_CHECKING

from rpa_recorder.classifier.heuristic import default_pipeline
from rpa_recorder.classifier.heuristic.classifiers import (
    ConfirmationClassifier,
    DismissModalClassifier,
    FormFillClassifier,
    FormSubmitClassifier,
    LoginClassifier,
    NavigationClassifier,
    SearchClassifier,
)
from rpa_recorder.classifier.heuristic.protocol import RuleContext
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


class TestLoginClassifier:
    def test_fires_on_password_field(self, make_action: Callable[..., RecordedAction]) -> None:
        action = make_action(
            sequence=0,
            action_type=ActionType.INPUT,
            payload=InputPayload(value="hunter2"),
            selector=ElementSelector(test_id="pw"),
            element_context=ElementContext(tag="input", attributes={"type": "password"}),
        )
        rule = LoginClassifier()
        ctx = RuleContext(actions=[action], index=0)
        verdict = rule.apply(action, ctx)
        assert verdict is not None
        assert verdict.intent is SemanticIntent.LOGIN
        assert verdict.confidence == 0.95
        assert verdict.source == "login"

    def test_abstains_on_non_input(self, make_action: Callable[..., RecordedAction]) -> None:
        action = make_action(sequence=0, action_type=ActionType.CLICK, payload=ClickPayload())
        rule = LoginClassifier()
        ctx = RuleContext(actions=[action], index=0)
        assert rule.apply(action, ctx) is None

    def test_abstains_on_non_password_input(
        self, make_action: Callable[..., RecordedAction]
    ) -> None:
        action = make_action(
            sequence=0,
            action_type=ActionType.INPUT,
            payload=InputPayload(value="alice"),
            element_context=ElementContext(tag="input", attributes={"type": "text"}),
        )
        rule = LoginClassifier()
        ctx = RuleContext(actions=[action], index=0)
        assert rule.apply(action, ctx) is None


class TestSearchClassifier:
    def test_fires_on_role_searchbox(self, make_action: Callable[..., RecordedAction]) -> None:
        action = make_action(
            sequence=0,
            action_type=ActionType.INPUT,
            payload=InputPayload(value="laptop"),
            selector=ElementSelector(role="searchbox"),
            element_context=ElementContext(tag="input"),
        )
        rule = SearchClassifier()
        ctx = RuleContext(actions=[action], index=0)
        verdict = rule.apply(action, ctx)
        assert verdict is not None
        assert verdict.intent is SemanticIntent.SEARCH
        assert verdict.confidence == 0.90

    def test_fires_on_type_search(self, make_action: Callable[..., RecordedAction]) -> None:
        action = make_action(
            sequence=0,
            action_type=ActionType.INPUT,
            payload=InputPayload(value="laptop"),
            element_context=ElementContext(tag="input", attributes={"type": "search"}),
        )
        rule = SearchClassifier()
        ctx = RuleContext(actions=[action], index=0)
        verdict = rule.apply(action, ctx)
        assert verdict is not None
        assert verdict.intent is SemanticIntent.SEARCH

    def test_fires_on_placeholder_contains_search(
        self, make_action: Callable[..., RecordedAction]
    ) -> None:
        action = make_action(
            sequence=0,
            action_type=ActionType.INPUT,
            payload=InputPayload(value="laptop"),
            element_context=ElementContext(
                tag="input", attributes={"placeholder": "Search products…"}
            ),
        )
        rule = SearchClassifier()
        ctx = RuleContext(actions=[action], index=0)
        verdict = rule.apply(action, ctx)
        assert verdict is not None
        assert verdict.intent is SemanticIntent.SEARCH

    def test_abstains_on_plain_text_input(self, make_action: Callable[..., RecordedAction]) -> None:
        action = make_action(
            sequence=0,
            action_type=ActionType.INPUT,
            payload=InputPayload(value="alice"),
            element_context=ElementContext(tag="input", attributes={"type": "text"}),
        )
        rule = SearchClassifier()
        ctx = RuleContext(actions=[action], index=0)
        assert rule.apply(action, ctx) is None


class TestFormSubmitClassifier:
    def test_fires_inside_form(self, make_action: Callable[..., RecordedAction]) -> None:
        action = make_action(
            sequence=0,
            action_type=ActionType.CLICK,
            payload=ClickPayload(),
            selector=ElementSelector(role="button", accessible_name="Submit"),
            element_context=ElementContext(tag="button", parent_form_id="loginForm"),
        )
        rule = FormSubmitClassifier()
        ctx = RuleContext(actions=[action], index=0)
        verdict = rule.apply(action, ctx)
        assert verdict is not None
        assert verdict.intent is SemanticIntent.FORM_SUBMIT
        assert verdict.confidence == 0.85

    def test_abstains_when_no_parent_form(self, make_action: Callable[..., RecordedAction]) -> None:
        action = make_action(
            sequence=0,
            action_type=ActionType.CLICK,
            payload=ClickPayload(),
            selector=ElementSelector(role="button", accessible_name="Submit"),
            element_context=ElementContext(tag="button", parent_form_id=None),
        )
        rule = FormSubmitClassifier()
        ctx = RuleContext(actions=[action], index=0)
        assert rule.apply(action, ctx) is None

    def test_abstains_on_non_submit_text(self, make_action: Callable[..., RecordedAction]) -> None:
        action = make_action(
            sequence=0,
            action_type=ActionType.CLICK,
            payload=ClickPayload(),
            selector=ElementSelector(role="button", accessible_name="Cancel"),
            element_context=ElementContext(tag="button", parent_form_id="f"),
        )
        rule = FormSubmitClassifier()
        ctx = RuleContext(actions=[action], index=0)
        assert rule.apply(action, ctx) is None

    def test_abstains_on_non_click(self, make_action: Callable[..., RecordedAction]) -> None:
        action = make_action(
            sequence=0, action_type=ActionType.INPUT, payload=InputPayload(value="x")
        )
        rule = FormSubmitClassifier()
        ctx = RuleContext(actions=[action], index=0)
        assert rule.apply(action, ctx) is None


class TestConfirmationClassifier:
    def test_fires_on_confirm_text(self, make_action: Callable[..., RecordedAction]) -> None:
        action = make_action(
            sequence=0,
            action_type=ActionType.CLICK,
            payload=ClickPayload(),
            selector=ElementSelector(role="button", accessible_name="Confirm"),
        )
        rule = ConfirmationClassifier()
        ctx = RuleContext(actions=[action], index=0)
        verdict = rule.apply(action, ctx)
        assert verdict is not None
        assert verdict.intent is SemanticIntent.CONFIRMATION
        assert verdict.confidence == 0.80

    def test_is_case_insensitive(self, make_action: Callable[..., RecordedAction]) -> None:
        rule = ConfirmationClassifier()
        for label in ("OK", "ok", "Ok"):
            action = make_action(
                sequence=0,
                action_type=ActionType.CLICK,
                payload=ClickPayload(),
                selector=ElementSelector(role="button", accessible_name=label),
            )
            ctx = RuleContext(actions=[action], index=0)
            verdict = rule.apply(action, ctx)
            assert verdict is not None, f"failed to fire on {label!r}"
            assert verdict.intent is SemanticIntent.CONFIRMATION

    def test_abstains_on_non_confirm_text(self, make_action: Callable[..., RecordedAction]) -> None:
        action = make_action(
            sequence=0,
            action_type=ActionType.CLICK,
            payload=ClickPayload(),
            selector=ElementSelector(role="button", accessible_name="Save"),
        )
        rule = ConfirmationClassifier()
        ctx = RuleContext(actions=[action], index=0)
        assert rule.apply(action, ctx) is None


class TestDismissModalClassifier:
    def test_fires_on_close_icon(self, make_action: Callable[..., RecordedAction]) -> None:
        action = make_action(
            sequence=0,
            action_type=ActionType.CLICK,
            payload=ClickPayload(),
            selector=ElementSelector(role="button", accessible_name="✕"),
            element_context=ElementContext(tag="button"),
        )
        rule = DismissModalClassifier()
        ctx = RuleContext(actions=[action], index=0)
        verdict = rule.apply(action, ctx)
        assert verdict is not None
        assert verdict.intent is SemanticIntent.DISMISS_MODAL
        assert verdict.confidence == 0.80

    def test_fires_on_aria_label(self, make_action: Callable[..., RecordedAction]) -> None:
        action = make_action(
            sequence=0,
            action_type=ActionType.CLICK,
            payload=ClickPayload(),
            selector=ElementSelector(role="button"),
            element_context=ElementContext(tag="button", attributes={"aria-label": "Close dialog"}),
        )
        rule = DismissModalClassifier()
        ctx = RuleContext(actions=[action], index=0)
        verdict = rule.apply(action, ctx)
        assert verdict is not None
        assert verdict.intent is SemanticIntent.DISMISS_MODAL

    def test_fires_on_close_class(self, make_action: Callable[..., RecordedAction]) -> None:
        action = make_action(
            sequence=0,
            action_type=ActionType.CLICK,
            payload=ClickPayload(),
            selector=ElementSelector(role="button"),
            element_context=ElementContext(tag="button", attributes={"class": "btn modal-close"}),
        )
        rule = DismissModalClassifier()
        ctx = RuleContext(actions=[action], index=0)
        verdict = rule.apply(action, ctx)
        assert verdict is not None
        assert verdict.intent is SemanticIntent.DISMISS_MODAL

    def test_abstains_on_unrelated_button(self, make_action: Callable[..., RecordedAction]) -> None:
        action = make_action(
            sequence=0,
            action_type=ActionType.CLICK,
            payload=ClickPayload(),
            selector=ElementSelector(role="button", accessible_name="Save"),
            element_context=ElementContext(tag="button"),
        )
        rule = DismissModalClassifier()
        ctx = RuleContext(actions=[action], index=0)
        assert rule.apply(action, ctx) is None


class TestNavigationClassifier:
    def test_always_fires_on_navigate(self, make_action: Callable[..., RecordedAction]) -> None:
        action = make_action(
            sequence=0,
            action_type=ActionType.NAVIGATE,
            payload=NavigatePayload(url="https://example.com"),
        )
        rule = NavigationClassifier()
        ctx = RuleContext(actions=[action], index=0)
        verdict = rule.apply(action, ctx)
        assert verdict is not None
        assert verdict.intent is SemanticIntent.NAVIGATION
        assert verdict.confidence == 1.00

    def test_abstains_on_non_navigate(self, make_action: Callable[..., RecordedAction]) -> None:
        action = make_action(sequence=0, action_type=ActionType.CLICK, payload=ClickPayload())
        rule = NavigationClassifier()
        ctx = RuleContext(actions=[action], index=0)
        assert rule.apply(action, ctx) is None


class TestFormFillClassifier:
    def test_is_catch_all(self, make_action: Callable[..., RecordedAction]) -> None:
        action = make_action(
            sequence=0,
            action_type=ActionType.INPUT,
            payload=InputPayload(value="alice"),
            element_context=ElementContext(tag="input", attributes={"type": "text"}),
        )
        rule = FormFillClassifier()
        ctx = RuleContext(actions=[action], index=0)
        verdict = rule.apply(action, ctx)
        assert verdict is not None
        assert verdict.intent is SemanticIntent.FORM_FILL
        assert verdict.confidence == 0.70

    def test_abstains_on_non_input(self, make_action: Callable[..., RecordedAction]) -> None:
        action = make_action(sequence=0, action_type=ActionType.CLICK, payload=ClickPayload())
        rule = FormFillClassifier()
        ctx = RuleContext(actions=[action], index=0)
        assert rule.apply(action, ctx) is None


class TestPipelineShadowing:
    def test_form_fill_loses_to_login_when_both_match(
        self, make_action: Callable[..., RecordedAction]
    ) -> None:
        action = make_action(
            sequence=0,
            action_type=ActionType.INPUT,
            payload=InputPayload(value="hunter2", is_sensitive=True),
            selector=ElementSelector(test_id="pw"),
            element_context=ElementContext(tag="input", attributes={"type": "password"}),
        )
        engine = default_pipeline()
        results = engine.process([action])
        assert len(results) == 1
        _, verdict = results[0]
        assert verdict.intent is SemanticIntent.LOGIN
        assert verdict.confidence == 0.95

    def test_classifier_abstains_when_action_type_does_not_match(
        self, make_action: Callable[..., RecordedAction]
    ) -> None:
        action = make_action(
            sequence=0,
            action_type=ActionType.NAVIGATE,
            payload=NavigatePayload(url="https://example.com"),
        )
        rule = LoginClassifier()
        ctx = RuleContext(actions=[action], index=0)
        assert rule.apply(action, ctx) is None
