"""Merge strategies."""

import pytest

from rpa_recorder.classifier.heuristic.protocol import ClassifyCandidate
from rpa_recorder.classifier.llm.merge import (
    HighestConfidenceMerge,
    VotingMerge,
    WeightedMerge,
)
from rpa_recorder.models import SemanticIntent


def _candidate(intent: SemanticIntent, conf: float, source: str = "rule") -> ClassifyCandidate:
    return ClassifyCandidate(intent=intent, confidence=conf, reasoning="r", source=source)


def test_highest_confidence_picks_winner() -> None:
    h = _candidate(SemanticIntent.LOGIN, 0.5, "login")
    l_ = _candidate(SemanticIntent.SEARCH, 0.9, "llm")
    final = HighestConfidenceMerge().merge(heuristic=h, llm=l_)
    assert final.intent is SemanticIntent.SEARCH
    assert final.confidence == pytest.approx(0.9)
    assert "merged:highest_confidence" in final.source


def test_highest_confidence_keeps_heuristic_when_higher() -> None:
    h = _candidate(SemanticIntent.LOGIN, 0.95, "login")
    l_ = _candidate(SemanticIntent.SEARCH, 0.4, "llm")
    final = HighestConfidenceMerge().merge(heuristic=h, llm=l_)
    assert final.intent is SemanticIntent.LOGIN
    assert final.source.startswith("heuristic:")


def test_highest_confidence_with_only_llm() -> None:
    final = HighestConfidenceMerge().merge(
        heuristic=None, llm=_candidate(SemanticIntent.LOGIN, 0.9)
    )
    assert final.intent is SemanticIntent.LOGIN


def test_highest_confidence_with_only_heuristic() -> None:
    final = HighestConfidenceMerge().merge(
        heuristic=_candidate(SemanticIntent.LOGIN, 0.9), llm=None
    )
    assert final.intent is SemanticIntent.LOGIN


def test_highest_confidence_with_both_none() -> None:
    final = HighestConfidenceMerge().merge(heuristic=None, llm=None)
    assert final.intent is SemanticIntent.UNKNOWN
    assert final.confidence == 0


def test_voting_agreement_keeps_max_confidence() -> None:
    h = _candidate(SemanticIntent.LOGIN, 0.6)
    l_ = _candidate(SemanticIntent.LOGIN, 0.8)
    final = VotingMerge().merge(heuristic=h, llm=l_)
    assert final.intent is SemanticIntent.LOGIN
    assert final.confidence == pytest.approx(0.8)
    assert final.source == "merged:voting"


def test_voting_disagreement_falls_back_to_llm() -> None:
    h = _candidate(SemanticIntent.LOGIN, 0.95)
    l_ = _candidate(SemanticIntent.SEARCH, 0.3)
    final = VotingMerge().merge(heuristic=h, llm=l_)
    assert final.intent is SemanticIntent.SEARCH


def test_weighted_blends_confidences_when_intent_agrees() -> None:
    h = _candidate(SemanticIntent.LOGIN, 0.6)
    l_ = _candidate(SemanticIntent.LOGIN, 0.8)
    final = WeightedMerge(weight_heuristic=0.4, weight_llm=0.6).merge(heuristic=h, llm=l_)
    assert final.intent is SemanticIntent.LOGIN
    # (0.6*0.4 + 0.8*0.6) / 1.0 = 0.72
    assert final.confidence == pytest.approx(0.72)


def test_weighted_picks_higher_score_on_disagreement() -> None:
    h = _candidate(SemanticIntent.LOGIN, 1.0)
    l_ = _candidate(SemanticIntent.SEARCH, 0.5)
    # Heuristic score = 1.0 * 0.4 = 0.4; LLM score = 0.5 * 0.6 = 0.3 → heuristic wins.
    final = WeightedMerge(weight_heuristic=0.4, weight_llm=0.6).merge(heuristic=h, llm=l_)
    assert final.intent is SemanticIntent.LOGIN


def test_weighted_rejects_invalid_weights() -> None:
    with pytest.raises(ValueError, match="weights"):
        WeightedMerge(weight_heuristic=-0.1, weight_llm=0.5)
    with pytest.raises(ValueError, match="weights"):
        WeightedMerge(weight_heuristic=0, weight_llm=0)
