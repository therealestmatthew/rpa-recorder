"""Tests for the three default normalizer rules."""

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from rpa_recorder.classifier.heuristic.normalizers import (
    CanonicalizeUrl,
    CoalesceInputBursts,
    TrimInputValue,
)
from rpa_recorder.classifier.heuristic.protocol import RuleContext
from rpa_recorder.models import (
    ActionType,
    ClickPayload,
    ElementSelector,
    InputPayload,
    NavigatePayload,
    RecordedAction,
)

if TYPE_CHECKING:
    from collections.abc import Callable

_FIXED_TS = datetime(2026, 5, 4, 12, 0, 0, tzinfo=UTC)


class TestTrimInputValue:
    def test_strips_whitespace(self, make_action: Callable[..., RecordedAction]) -> None:
        action = make_action(
            sequence=0,
            action_type=ActionType.INPUT,
            payload=InputPayload(value="  alice  "),
        )
        rule = TrimInputValue()
        ctx = RuleContext(actions=[action], index=0)
        out = rule.apply(action, ctx)
        assert isinstance(out.payload, InputPayload)
        assert out.payload.value == "alice"

    def test_preserves_sensitive(self, make_action: Callable[..., RecordedAction]) -> None:
        action = make_action(
            sequence=0,
            action_type=ActionType.INPUT,
            payload=InputPayload(value="  hunter2  ", is_sensitive=True),
        )
        rule = TrimInputValue()
        ctx = RuleContext(actions=[action], index=0)
        out = rule.apply(action, ctx)
        assert isinstance(out.payload, InputPayload)
        assert out.payload.value == "  hunter2  "

    def test_passes_non_input_through(self, make_action: Callable[..., RecordedAction]) -> None:
        action = make_action(
            sequence=0,
            action_type=ActionType.CLICK,
            payload=ClickPayload(),
        )
        rule = TrimInputValue()
        ctx = RuleContext(actions=[action], index=0)
        assert rule.apply(action, ctx) is action

    def test_no_op_when_already_trimmed(self, make_action: Callable[..., RecordedAction]) -> None:
        action = make_action(
            sequence=0,
            action_type=ActionType.INPUT,
            payload=InputPayload(value="alice"),
        )
        rule = TrimInputValue()
        ctx = RuleContext(actions=[action], index=0)
        assert rule.apply(action, ctx) is action


class TestCoalesceInputBursts:
    def test_merges_rapid_typing(self, make_action: Callable[..., RecordedAction]) -> None:
        sel = ElementSelector(test_id="email")
        actions = [
            make_action(
                sequence=0,
                offset_ms=0,
                action_type=ActionType.INPUT,
                payload=InputPayload(value="a"),
                selector=sel,
            ),
            make_action(
                sequence=1,
                offset_ms=50,
                action_type=ActionType.INPUT,
                payload=InputPayload(value="al"),
                selector=sel,
            ),
            make_action(
                sequence=2,
                offset_ms=100,
                action_type=ActionType.INPUT,
                payload=InputPayload(value="ali"),
                selector=sel,
            ),
        ]
        rule = CoalesceInputBursts()
        ctx = RuleContext(actions=actions, index=0)
        out = rule.apply(actions[0], ctx)
        assert isinstance(out.payload, InputPayload)
        assert out.payload.value == "ali"
        assert ctx.scratch["coalesced_indexes"] == {1, 2}

    def test_keeps_separate_when_gap_exceeds_threshold(
        self, make_action: Callable[..., RecordedAction]
    ) -> None:
        sel = ElementSelector(test_id="email")
        actions = [
            make_action(
                sequence=0,
                offset_ms=0,
                action_type=ActionType.INPUT,
                payload=InputPayload(value="a"),
                selector=sel,
            ),
            make_action(
                sequence=1,
                offset_ms=500,
                action_type=ActionType.INPUT,
                payload=InputPayload(value="b"),
                selector=sel,
            ),
        ]
        rule = CoalesceInputBursts()
        ctx = RuleContext(actions=actions, index=0)
        out = rule.apply(actions[0], ctx)
        assert isinstance(out.payload, InputPayload)
        assert out.payload.value == "a"
        assert ctx.scratch.get("coalesced_indexes", set()) == set()

    def test_passes_non_input_through(self, make_action: Callable[..., RecordedAction]) -> None:
        action = make_action(
            sequence=0,
            action_type=ActionType.CLICK,
            payload=ClickPayload(),
        )
        rule = CoalesceInputBursts()
        ctx = RuleContext(actions=[action], index=0)
        assert rule.apply(action, ctx) is action

    def test_follower_returns_unchanged(self, make_action: Callable[..., RecordedAction]) -> None:
        # When the rule is applied to an action already marked as a follower,
        # it returns the action untouched (the leader is responsible for the merge).
        sel = ElementSelector(test_id="email")
        leader = make_action(
            sequence=0,
            offset_ms=0,
            action_type=ActionType.INPUT,
            payload=InputPayload(value="a"),
            selector=sel,
        )
        follower = make_action(
            sequence=1,
            offset_ms=50,
            action_type=ActionType.INPUT,
            payload=InputPayload(value="al"),
            selector=sel,
        )
        rule = CoalesceInputBursts()
        ctx = RuleContext(actions=[leader, follower], index=1)
        ctx.scratch["coalesced_indexes"] = {1}
        assert rule.apply(follower, ctx) is follower

    def test_no_op_when_burst_last_value_matches_leader(
        self, make_action: Callable[..., RecordedAction]
    ) -> None:
        # Burst where the LAST follower's value equals the leader's value
        # (e.g. the user typed and immediately backspaced). The leader is
        # returned unchanged but followers are still marked for drop.
        sel = ElementSelector(test_id="email")
        leader = make_action(
            sequence=0,
            offset_ms=0,
            action_type=ActionType.INPUT,
            payload=InputPayload(value="a"),
            selector=sel,
        )
        follower = make_action(
            sequence=1,
            offset_ms=50,
            action_type=ActionType.INPUT,
            payload=InputPayload(value="a"),
            selector=sel,
        )
        rule = CoalesceInputBursts()
        ctx = RuleContext(actions=[leader, follower], index=0)
        out = rule.apply(leader, ctx)
        assert out is leader
        assert ctx.scratch["coalesced_indexes"] == {1}


class TestCanonicalizeUrl:
    def test_lowercases_scheme_and_host(self, make_action: Callable[..., RecordedAction]) -> None:
        action = make_action(
            sequence=0,
            action_type=ActionType.NAVIGATE,
            payload=NavigatePayload(url="HTTP://Example.COM/"),
        )
        rule = CanonicalizeUrl()
        ctx = RuleContext(actions=[action], index=0)
        out = rule.apply(action, ctx)
        assert isinstance(out.payload, NavigatePayload)
        assert out.payload.url == "http://example.com/"

    def test_sorts_query_params(self, make_action: Callable[..., RecordedAction]) -> None:
        action = make_action(
            sequence=0,
            action_type=ActionType.NAVIGATE,
            payload=NavigatePayload(url="https://x.com/?b=2&a=1"),
        )
        rule = CanonicalizeUrl()
        ctx = RuleContext(actions=[action], index=0)
        out = rule.apply(action, ctx)
        assert isinstance(out.payload, NavigatePayload)
        assert out.payload.url == "https://x.com/?a=1&b=2"

    def test_preserves_hash_fragment(self, make_action: Callable[..., RecordedAction]) -> None:
        action = make_action(
            sequence=0,
            action_type=ActionType.NAVIGATE,
            payload=NavigatePayload(url="https://x.com/#section"),
        )
        rule = CanonicalizeUrl()
        ctx = RuleContext(actions=[action], index=0)
        out = rule.apply(action, ctx)
        assert isinstance(out.payload, NavigatePayload)
        assert out.payload.url == "https://x.com/#section"

    def test_strips_trailing_slash_from_non_root_path(
        self, make_action: Callable[..., RecordedAction]
    ) -> None:
        action = make_action(
            sequence=0,
            action_type=ActionType.NAVIGATE,
            payload=NavigatePayload(url="https://x.com/foo/"),
        )
        rule = CanonicalizeUrl()
        ctx = RuleContext(actions=[action], index=0)
        out = rule.apply(action, ctx)
        assert isinstance(out.payload, NavigatePayload)
        assert out.payload.url == "https://x.com/foo"

    def test_passes_non_navigate_through(self, make_action: Callable[..., RecordedAction]) -> None:
        action = make_action(sequence=0, action_type=ActionType.CLICK, payload=ClickPayload())
        rule = CanonicalizeUrl()
        ctx = RuleContext(actions=[action], index=0)
        assert rule.apply(action, ctx) is action


class TestNormalizerDefensivePaths:
    """Branches reached only when payload bypasses Pydantic union resolution.

    `RecordedAction.model_construct` skips validation, so callers loading
    pre-validated bronze data can preserve raw dict payloads. The rules
    pass them through unchanged.
    """

    def test_trim_input_value_passes_dict_payload_through(self) -> None:
        action = RecordedAction.model_construct(
            sequence=0,
            timestamp=_FIXED_TS,
            action_type=ActionType.INPUT,
            payload={"foo": "bar"},
            url="https://example.com",
        )
        rule = TrimInputValue()
        ctx = RuleContext(actions=[action], index=0)
        assert rule.apply(action, ctx) is action

    def test_canonicalize_url_passes_dict_payload_through(self) -> None:
        action = RecordedAction.model_construct(
            sequence=0,
            timestamp=_FIXED_TS,
            action_type=ActionType.NAVIGATE,
            payload={"url": "https://example.com"},
            url="about:blank",
        )
        rule = CanonicalizeUrl()
        ctx = RuleContext(actions=[action], index=0)
        assert rule.apply(action, ctx) is action

    def test_coalesce_passes_dict_payload_through(self) -> None:
        action = RecordedAction.model_construct(
            sequence=0,
            timestamp=_FIXED_TS,
            action_type=ActionType.INPUT,
            payload={"foo": "bar"},
            url="https://example.com",
        )
        rule = CoalesceInputBursts()
        ctx = RuleContext(actions=[action], index=0)
        assert rule.apply(action, ctx) is action

    def test_coalesce_breaks_burst_on_dict_follower(
        self, make_action: Callable[..., RecordedAction]
    ) -> None:
        sel = ElementSelector(test_id="email")
        leader = make_action(
            sequence=0,
            offset_ms=0,
            action_type=ActionType.INPUT,
            payload=InputPayload(value="a"),
            selector=sel,
        )
        bad_follower = RecordedAction.model_construct(
            sequence=1,
            timestamp=_FIXED_TS,
            action_type=ActionType.INPUT,
            payload={"foo": "bar"},
            url="https://example.com",
            selector=sel,
        )
        rule = CoalesceInputBursts()
        ctx = RuleContext(actions=[leader, bad_follower], index=0)
        out = rule.apply(leader, ctx)
        # Burst broke at the dict-payload follower; nothing coalesced.
        assert out is leader
        assert ctx.scratch.get("coalesced_indexes", set()) == set()
