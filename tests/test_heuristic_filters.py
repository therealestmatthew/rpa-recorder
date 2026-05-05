"""Tests for the four default filter rules."""

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from rpa_recorder.classifier.heuristic import default_pipeline
from rpa_recorder.classifier.heuristic.filters import (
    DropCoalescedFollowers,
    DropDisabledTarget,
    DropDuplicateNavigate,
    DropFocusBlurOnly,
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
)

if TYPE_CHECKING:
    from collections.abc import Callable

_FIXED_TS = datetime(2026, 5, 4, 12, 0, 0, tzinfo=UTC)


class TestDropFocusBlurOnly:
    def test_drops_empty_input_with_no_followup(
        self, make_action: Callable[..., RecordedAction]
    ) -> None:
        focus_email = make_action(
            sequence=0,
            action_type=ActionType.INPUT,
            payload=InputPayload(value=""),
            selector=ElementSelector(test_id="email"),
            element_context=ElementContext(tag="input"),
        )
        click = make_action(
            sequence=1,
            offset_ms=10_000,
            action_type=ActionType.CLICK,
            payload=ClickPayload(),
            selector=ElementSelector(role="button", accessible_name="Continue"),
            element_context=ElementContext(tag="button", parent_form_id="f"),
        )
        focus_name = make_action(
            sequence=2,
            offset_ms=20_000,
            action_type=ActionType.INPUT,
            payload=InputPayload(value=""),
            selector=ElementSelector(test_id="name"),
            element_context=ElementContext(tag="input"),
        )
        engine = default_pipeline()
        results = engine.process([focus_email, click, focus_name])
        assert len(results) == 1
        assert results[0][0].sequence == 1

    def test_keeps_input_with_followup_typing(
        self, make_action: Callable[..., RecordedAction]
    ) -> None:
        # The "empty" focus is followed within 200 ms by a real typing event;
        # the rule keeps the empty one because a follow-up exists within 2000 ms.
        focus = make_action(
            sequence=0,
            action_type=ActionType.INPUT,
            payload=InputPayload(value=""),
            selector=ElementSelector(test_id="email"),
            element_context=ElementContext(tag="input"),
        )
        typed = make_action(
            sequence=1,
            offset_ms=150,
            action_type=ActionType.INPUT,
            payload=InputPayload(value="a"),
            selector=ElementSelector(test_id="email"),
            element_context=ElementContext(tag="input"),
        )
        rule = DropFocusBlurOnly()
        ctx = RuleContext(actions=[focus, typed], index=0)
        assert rule.apply(focus, ctx) is True

    def test_drops_when_followup_typing_is_outside_window(
        self, make_action: Callable[..., RecordedAction]
    ) -> None:
        # Same selector but the typing follow-up arrives after the 2000 ms
        # window, so the rule treats the focus as orphaned and drops it.
        focus = make_action(
            sequence=0,
            action_type=ActionType.INPUT,
            payload=InputPayload(value=""),
            selector=ElementSelector(test_id="email"),
            element_context=ElementContext(tag="input"),
        )
        late_typed = make_action(
            sequence=1,
            offset_ms=3000,
            action_type=ActionType.INPUT,
            payload=InputPayload(value="a"),
            selector=ElementSelector(test_id="email"),
            element_context=ElementContext(tag="input"),
        )
        rule = DropFocusBlurOnly()
        ctx = RuleContext(actions=[focus, late_typed], index=0)
        assert rule.apply(focus, ctx) is False


class TestDropDuplicateNavigate:
    def test_drops_consecutive_same_url(self, make_action: Callable[..., RecordedAction]) -> None:
        first = make_action(
            sequence=0,
            action_type=ActionType.NAVIGATE,
            payload=NavigatePayload(url="https://example.com/home"),
        )
        second = make_action(
            sequence=1,
            offset_ms=1000,
            action_type=ActionType.NAVIGATE,
            payload=NavigatePayload(url="https://example.com/home"),
        )
        engine = default_pipeline()
        results = engine.process([first, second])
        assert len(results) == 1
        assert results[0][0].sequence == 0

    def test_keeps_navigate_when_url_differs(
        self, make_action: Callable[..., RecordedAction]
    ) -> None:
        first = make_action(
            sequence=0,
            action_type=ActionType.NAVIGATE,
            payload=NavigatePayload(url="https://example.com/home"),
        )
        second = make_action(
            sequence=1,
            offset_ms=1000,
            action_type=ActionType.NAVIGATE,
            payload=NavigatePayload(url="https://example.com/profile"),
        )
        rule = DropDuplicateNavigate()
        ctx = RuleContext(actions=[first, second], index=1)
        assert rule.apply(second, ctx) is True


class TestDropDisabledTarget:
    def test_drops_disabled_action(self, make_action: Callable[..., RecordedAction]) -> None:
        disabled = make_action(
            sequence=0,
            action_type=ActionType.INPUT,
            payload=InputPayload(value="x"),
            element_context=ElementContext(tag="input", is_enabled=False),
        )
        rule = DropDisabledTarget()
        ctx = RuleContext(actions=[disabled], index=0)
        assert rule.apply(disabled, ctx) is False

    def test_keeps_enabled_action(self, make_action: Callable[..., RecordedAction]) -> None:
        enabled = make_action(
            sequence=0,
            action_type=ActionType.INPUT,
            payload=InputPayload(value="x"),
            element_context=ElementContext(tag="input", is_enabled=True),
        )
        rule = DropDisabledTarget()
        ctx = RuleContext(actions=[enabled], index=0)
        assert rule.apply(enabled, ctx) is True

    def test_keeps_action_without_element_context(
        self, make_action: Callable[..., RecordedAction]
    ) -> None:
        action = make_action(sequence=0)
        rule = DropDisabledTarget()
        ctx = RuleContext(actions=[action], index=0)
        assert rule.apply(action, ctx) is True


class TestDropCoalescedFollowers:
    def test_consumes_scratch(self, make_action: Callable[..., RecordedAction]) -> None:
        actions = [
            make_action(sequence=1, action_type=ActionType.INPUT, payload=InputPayload(value="a")),
            make_action(sequence=2, action_type=ActionType.INPUT, payload=InputPayload(value="b")),
            make_action(sequence=3, action_type=ActionType.INPUT, payload=InputPayload(value="c")),
            make_action(sequence=4, action_type=ActionType.INPUT, payload=InputPayload(value="d")),
        ]
        rule = DropCoalescedFollowers()
        ctx = RuleContext(actions=actions, index=0)
        ctx.scratch["coalesced_indexes"] = {2, 3}
        verdicts = [rule.apply(a, ctx) for a in actions]
        assert verdicts == [True, False, False, True]

    def test_keeps_all_when_scratch_empty(self, make_action: Callable[..., RecordedAction]) -> None:
        a = make_action(sequence=0, action_type=ActionType.INPUT, payload=InputPayload(value="x"))
        rule = DropCoalescedFollowers()
        ctx = RuleContext(actions=[a], index=0)
        assert rule.apply(a, ctx) is True


class TestFilterDefensivePaths:
    """Branches reached only when payload bypasses Pydantic union resolution.

    `RecordedAction.model_construct` skips validation, so callers loading
    pre-validated bronze data can preserve raw dict payloads. The rules
    handle that gracefully.
    """

    def test_drop_focus_blur_only_keeps_input_with_dict_payload(self) -> None:
        action = RecordedAction.model_construct(
            sequence=0,
            timestamp=_FIXED_TS,
            action_type=ActionType.INPUT,
            payload={"foo": "bar"},
            url="https://example.com",
        )
        rule = DropFocusBlurOnly()
        ctx = RuleContext(actions=[action], index=0)
        assert rule.apply(action, ctx) is True

    def test_drop_duplicate_navigate_handles_dict_payload(self) -> None:
        first = RecordedAction.model_construct(
            sequence=0,
            timestamp=_FIXED_TS,
            action_type=ActionType.NAVIGATE,
            payload={"url": "https://example.com/home"},
            url="about:blank",
        )
        second = RecordedAction.model_construct(
            sequence=1,
            timestamp=_FIXED_TS,
            action_type=ActionType.NAVIGATE,
            payload={"url": "https://example.com/home"},
            url="https://example.com/home",
        )
        rule = DropDuplicateNavigate()
        ctx = RuleContext(actions=[first, second], index=1)
        assert rule.apply(second, ctx) is False

    def test_drop_duplicate_navigate_handles_dict_payload_without_url(self) -> None:
        action = RecordedAction.model_construct(
            sequence=0,
            timestamp=_FIXED_TS,
            action_type=ActionType.NAVIGATE,
            payload={"foo": "bar"},
            url="about:blank",
        )
        rule = DropDuplicateNavigate()
        ctx = RuleContext(actions=[action], index=0)
        assert rule.apply(action, ctx) is True

    def test_drop_duplicate_navigate_handles_dict_payload_with_non_string_url(self) -> None:
        action = RecordedAction.model_construct(
            sequence=0,
            timestamp=_FIXED_TS,
            action_type=ActionType.NAVIGATE,
            payload={"url": 123},
            url="about:blank",
        )
        rule = DropDuplicateNavigate()
        ctx = RuleContext(actions=[action], index=0)
        assert rule.apply(action, ctx) is True

    def test_drop_duplicate_navigate_handles_unrecognized_payload_type(self) -> None:
        # NAVIGATE action with a non-NavigatePayload, non-dict payload (e.g. a
        # ClickPayload from a misclassified bronze record). `_navigate_url`
        # falls through to its final `return None` and the action is kept.
        action = RecordedAction.model_construct(
            sequence=0,
            timestamp=_FIXED_TS,
            action_type=ActionType.NAVIGATE,
            payload=ClickPayload(),
            url="about:blank",
        )
        rule = DropDuplicateNavigate()
        ctx = RuleContext(actions=[action], index=0)
        assert rule.apply(action, ctx) is True
