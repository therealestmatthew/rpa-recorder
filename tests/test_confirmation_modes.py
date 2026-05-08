"""Tests for the M11 confirmation review modes."""

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from rpa_recorder.confirmation import ActionReviewResult, Decision
from rpa_recorder.confirmation.modes import (
    DiffBaselineMode,
    OverviewMode,
    PerActionMode,
    PerIntentBatchMode,
    default_mode,
)
from rpa_recorder.confirmation.renderers import CompactRenderer
from rpa_recorder.models import (
    ActionType,
    ClickPayload,
    RecordedAction,
    SemanticIntent,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    import pytest


def _make_action(
    *,
    sequence: int = 0,
    intent: SemanticIntent = SemanticIntent.UNKNOWN,
    confidence: float = 0.4,
    timestamp: datetime | None = None,
) -> RecordedAction:
    return RecordedAction(
        sequence=sequence,
        timestamp=timestamp or datetime(2026, 5, 6, tzinfo=UTC),
        action_type=ActionType.CLICK,
        payload=ClickPayload(),
        url="https://example.com",
        semantic_intent=intent,
        classification_confidence=confidence,
    )


def _scripted_prompt(monkeypatch: pytest.MonkeyPatch, answers: list[str]) -> None:
    """Patch every `Prompt.ask` call to return scripted responses in order."""
    iterator: Iterator[str] = iter(answers)

    def fake_ask(*_args: object, **_kwargs: object) -> str:
        try:
            return next(iterator)
        except StopIteration as exc:  # pragma: no cover — surfaces test bugs
            msg = "scripted prompt exhausted"
            raise AssertionError(msg) from exc

    # Patch every site that imports Prompt — modes import from the same
    # module so a single patch catches both.
    monkeypatch.setattr("rpa_recorder.confirmation.modes.per_action.Prompt.ask", fake_ask)
    monkeypatch.setattr("rpa_recorder.confirmation.modes.per_intent_batch.Prompt.ask", fake_ask)
    monkeypatch.setattr("rpa_recorder.confirmation.modes.overview.Prompt.ask", fake_ask)


async def _drain(mode: object, candidates: list[RecordedAction]) -> list[ActionReviewResult]:
    captured: list[ActionReviewResult] = []

    async def on_decision(result: ActionReviewResult) -> None:
        captured.append(result)

    return await mode.review(  # type: ignore[attr-defined,no-any-return]
        candidates,
        renderer=CompactRenderer(),
        on_decision=on_decision,
    )


async def test_per_action_dispatches_decision_per_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _scripted_prompt(monkeypatch, ["a", "r", "search", "s"])
    a, b, c = (
        _make_action(sequence=0),
        _make_action(sequence=1),
        _make_action(sequence=2),
    )
    results = await _drain(PerActionMode(), [a, b, c])
    assert [r.decision for r in results] == [
        Decision.ACCEPT,
        Decision.RELABEL,
        Decision.SKIP,
    ]
    assert results[1].new_label is SemanticIntent.SEARCH


async def test_per_action_invokes_on_decision_per_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _scripted_prompt(monkeypatch, ["a", "a"])
    captured: list[ActionReviewResult] = []

    async def on_decision(result: ActionReviewResult) -> None:
        captured.append(result)

    actions = [_make_action(sequence=0), _make_action(sequence=1)]
    await PerActionMode().review(actions, renderer=CompactRenderer(), on_decision=on_decision)
    assert len(captured) == 2


async def test_per_intent_batch_groups_by_intent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Two intent groups; both accept all.
    _scripted_prompt(monkeypatch, ["a", "a"])
    actions = [
        _make_action(sequence=0, intent=SemanticIntent.SEARCH),
        _make_action(sequence=1, intent=SemanticIntent.LOGIN),
        _make_action(sequence=2, intent=SemanticIntent.SEARCH),
    ]
    results = await _drain(PerIntentBatchMode(), actions)
    assert len(results) == 3
    assert all(r.decision is Decision.ACCEPT for r in results)


async def test_per_intent_batch_falls_back_to_per_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # First group: review-each → falls back to per_action; supply per-action answers.
    _scripted_prompt(monkeypatch, ["r", "a", "s"])
    actions = [
        _make_action(sequence=0, intent=SemanticIntent.SEARCH),
        _make_action(sequence=1, intent=SemanticIntent.SEARCH),
    ]
    results = await _drain(PerIntentBatchMode(), actions)
    assert [r.decision for r in results] == [Decision.ACCEPT, Decision.SKIP]


async def test_per_intent_batch_custom_relabel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _scripted_prompt(monkeypatch, ["c", "login"])
    actions = [
        _make_action(sequence=0, intent=SemanticIntent.UNKNOWN),
        _make_action(sequence=1, intent=SemanticIntent.UNKNOWN),
    ]
    results = await _drain(PerIntentBatchMode(), actions)
    assert all(r.decision is Decision.RELABEL for r in results)
    assert all(r.new_label is SemanticIntent.LOGIN for r in results)


async def test_overview_auto_accepts_above_cutoff_then_per_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _scripted_prompt(monkeypatch, ["0.9", "s"])
    actions = [
        _make_action(sequence=0, confidence=0.95),
        _make_action(sequence=1, confidence=0.4),
    ]
    results = await _drain(OverviewMode(), actions)
    assert [r.decision for r in results] == [Decision.ACCEPT, Decision.SKIP]


async def test_diff_baseline_filters_by_intent_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _scripted_prompt(monkeypatch, ["a"])
    a = _make_action(sequence=0, intent=SemanticIntent.SEARCH)
    b = _make_action(sequence=1, intent=SemanticIntent.LOGIN)
    baseline = {str(a.id): "search", str(b.id): "search"}  # only b changed
    mode = DiffBaselineMode(
        baseline_at=datetime(2026, 5, 6, tzinfo=UTC),
        baseline_intents=baseline,
    )
    results = await _drain(mode, [a, b])
    assert len(results) == 1
    assert results[0].action_id == b.id


async def test_diff_baseline_falls_back_when_no_baseline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _scripted_prompt(monkeypatch, ["a", "a"])
    actions = [_make_action(sequence=0), _make_action(sequence=1)]
    mode = DiffBaselineMode(baseline_at=datetime(2026, 5, 6, tzinfo=UTC))
    results = await _drain(mode, actions)
    assert len(results) == 2


def test_default_mode_is_per_action() -> None:
    assert isinstance(default_mode(), PerActionMode)
