"""Tests for the M11 confirmation filters."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from rpa_recorder.confirmation.filters import (
    BelowThresholdFilter,
    ByIntentFilter,
    FailedOnReplayFilter,
    SinceDateFilter,
    UnconfirmedOnlyFilter,
    default_filter,
)
from rpa_recorder.models import (
    ActionType,
    ClickPayload,
    RecordedAction,
    Recording,
    SemanticIntent,
)


def _make_action(
    *,
    sequence: int = 0,
    confidence: float = 0.5,
    intent: SemanticIntent = SemanticIntent.UNKNOWN,
    user_confirmed: bool = False,
    timestamp: datetime | None = None,
) -> RecordedAction:
    return RecordedAction(
        sequence=sequence,
        timestamp=timestamp or datetime(2026, 5, 6, 12, 0, tzinfo=UTC),
        action_type=ActionType.CLICK,
        payload=ClickPayload(),
        url="https://example.com",
        semantic_intent=intent,
        classification_confidence=confidence,
        user_confirmed=user_confirmed,
    )


def _make_recording(actions: list[RecordedAction]) -> Recording:
    return Recording(
        id=uuid4(),
        name="t",
        created_at=datetime(2026, 5, 6, tzinfo=UTC),
        starting_url="https://example.com",
        actions=actions,
    )


def test_below_threshold_selects_only_below_cutoff() -> None:
    rec = _make_recording(
        [
            _make_action(sequence=0, confidence=0.5),
            _make_action(sequence=1, confidence=0.7),
            _make_action(sequence=2, confidence=0.95),
        ]
    )
    selected = BelowThresholdFilter().select(rec, threshold=0.7)
    assert [a.sequence for a in selected] == [0]


def test_by_intent_selects_matching_intent() -> None:
    rec = _make_recording(
        [
            _make_action(sequence=0, intent=SemanticIntent.SEARCH),
            _make_action(sequence=1, intent=SemanticIntent.LOGIN),
            _make_action(sequence=2, intent=SemanticIntent.SEARCH),
        ]
    )
    selected = ByIntentFilter(SemanticIntent.SEARCH).select(rec, threshold=0.7)
    assert [a.sequence for a in selected] == [0, 2]


def test_unconfirmed_only_filters_already_confirmed() -> None:
    rec = _make_recording(
        [
            _make_action(sequence=0, user_confirmed=True),
            _make_action(sequence=1, user_confirmed=False),
        ]
    )
    selected = UnconfirmedOnlyFilter().select(rec, threshold=0.7)
    assert [a.sequence for a in selected] == [1]


def test_since_date_filter_selects_actions_after_cutoff() -> None:
    base = datetime(2026, 5, 6, 12, 0, tzinfo=UTC)
    rec = _make_recording(
        [
            _make_action(sequence=0, timestamp=base),
            _make_action(sequence=1, timestamp=base + timedelta(hours=2)),
            _make_action(sequence=2, timestamp=base + timedelta(hours=5)),
        ]
    )
    cutoff = base + timedelta(hours=1)
    selected = SinceDateFilter(cutoff).select(rec, threshold=0.7)
    assert [a.sequence for a in selected] == [1, 2]


def test_failed_on_replay_uses_supplied_id_set() -> None:
    a = _make_action(sequence=0)
    b = _make_action(sequence=1)
    rec = _make_recording([a, b])
    selected = FailedOnReplayFilter([a.id]).select(rec, threshold=0.7)
    assert [act.id for act in selected] == [a.id]


def test_default_filter_returns_below_threshold_by_default() -> None:
    flt = default_filter()
    assert isinstance(flt, BelowThresholdFilter)


def test_default_filter_constructs_by_name() -> None:
    flt = default_filter("by_intent", intent=SemanticIntent.SEARCH)
    assert isinstance(flt, ByIntentFilter)
