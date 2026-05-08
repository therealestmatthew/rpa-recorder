"""Tests for the M11 confirmation protocol layer."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from rpa_recorder.confirmation import ActionReviewResult, Decision, ReviewSummary
from rpa_recorder.models import SemanticIntent


def test_decision_enum_values() -> None:
    assert Decision.ACCEPT.value == "accept"
    assert Decision.RELABEL.value == "relabel"
    assert Decision.SKIP.value == "skip"


def test_action_review_result_round_trips() -> None:
    original = ActionReviewResult(
        action_id=uuid4(),
        decision=Decision.RELABEL,
        new_label=SemanticIntent.SEARCH,
        reviewed_at=datetime(2026, 5, 6, tzinfo=UTC),
    )
    payload = original.model_dump()
    restored = ActionReviewResult.model_validate(payload)
    assert restored == original


def test_review_summary_holds_results() -> None:
    summary = ReviewSummary(
        recording_id=uuid4(),
        total_candidates=3,
        accepted=2,
        relabeled=1,
        skipped=0,
        duration_s=4.5,
    )
    assert summary.total_candidates == 3
    assert summary.accepted + summary.relabeled + summary.skipped == 3
    assert summary.results == []


def test_action_review_result_relabel_requires_no_validation_of_new_label() -> None:
    # The runner is responsible for enforcing relabel-needs-new_label;
    # the model itself stays liberal so SKIP/ACCEPT remain trivial.
    result = ActionReviewResult(
        action_id=uuid4(),
        decision=Decision.ACCEPT,
        reviewed_at=datetime(2026, 5, 6, tzinfo=UTC),
    )
    assert result.new_label is None


@pytest.mark.parametrize(
    "decision",
    [Decision.ACCEPT, Decision.RELABEL, Decision.SKIP],
)
def test_decision_string_round_trip(decision: Decision) -> None:
    assert Decision(decision.value) is decision
