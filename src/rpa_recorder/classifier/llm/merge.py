"""Merge strategies for combining a heuristic verdict with an LLM verdict.

Each strategy collapses an optional heuristic `ClassifyCandidate` and an
optional LLM `ClassifyCandidate` into a final `Classification`. The
`source` field gets a `merged:<strategy>` prefix (or `heuristic:<rule>` /
`llm` when only one side produced a verdict).
"""

from __future__ import annotations

from rpa_recorder.classifier.heuristic.protocol import Classification, ClassifyCandidate
from rpa_recorder.models import SemanticIntent

_UNKNOWN = Classification(
    intent=SemanticIntent.UNKNOWN,
    confidence=0.0,
    reasoning="no candidates",
    source="default",
)


def _from(candidate: ClassifyCandidate, *, source_override: str | None = None) -> Classification:
    return Classification(
        intent=candidate.intent,
        confidence=candidate.confidence,
        reasoning=candidate.reasoning,
        source=source_override if source_override is not None else candidate.source,
    )


class HighestConfidenceMerge:
    """Pick whichever side has higher confidence. Ties favour the LLM."""

    name: str = "highest_confidence"

    def merge(
        self,
        heuristic: ClassifyCandidate | None,
        llm: ClassifyCandidate | None,
    ) -> Classification:
        if heuristic is None and llm is None:
            return _UNKNOWN
        if heuristic is None:
            assert llm is not None
            return _from(llm, source_override=f"llm (merged:{self.name})")
        if llm is None:
            return _from(heuristic, source_override=f"heuristic:{heuristic.source}")
        if llm.confidence >= heuristic.confidence:
            return _from(llm, source_override=f"llm (merged:{self.name})")
        return _from(heuristic, source_override=f"heuristic:{heuristic.source}")


class VotingMerge:
    """Both must agree on intent → take that intent at max(conf). Else LLM wins."""

    name: str = "voting"

    def merge(
        self,
        heuristic: ClassifyCandidate | None,
        llm: ClassifyCandidate | None,
    ) -> Classification:
        if heuristic is None and llm is None:
            return _UNKNOWN
        if heuristic is None:
            assert llm is not None
            return _from(llm, source_override=f"llm (merged:{self.name})")
        if llm is None:
            return _from(heuristic, source_override=f"heuristic:{heuristic.source}")
        if heuristic.intent is llm.intent:
            return Classification(
                intent=llm.intent,
                confidence=max(heuristic.confidence, llm.confidence),
                reasoning=f"agreement: {llm.reasoning}",
                source=f"merged:{self.name}",
            )
        return _from(llm, source_override=f"llm (merged:{self.name})")


class WeightedMerge:
    """Blend confidences by weight; pick the side whose blended score is higher."""

    name: str = "weighted"

    def __init__(self, *, weight_heuristic: float = 0.4, weight_llm: float = 0.6) -> None:
        if weight_heuristic < 0 or weight_llm < 0:
            raise ValueError("weights must be ≥ 0")
        if weight_heuristic + weight_llm == 0:
            raise ValueError("weights cannot both be zero")
        self._wh = weight_heuristic
        self._wl = weight_llm

    def merge(
        self,
        heuristic: ClassifyCandidate | None,
        llm: ClassifyCandidate | None,
    ) -> Classification:
        if heuristic is None and llm is None:
            return _UNKNOWN
        if heuristic is None:
            assert llm is not None
            return _from(llm, source_override=f"llm (merged:{self.name})")
        if llm is None:
            return _from(heuristic, source_override=f"heuristic:{heuristic.source}")
        h_score = heuristic.confidence * self._wh
        l_score = llm.confidence * self._wl
        if heuristic.intent is llm.intent:
            blended = (heuristic.confidence * self._wh + llm.confidence * self._wl) / (
                self._wh + self._wl
            )
            return Classification(
                intent=llm.intent,
                confidence=blended,
                reasoning=f"weighted-agreement: {llm.reasoning}",
                source=f"merged:{self.name}",
            )
        winner = llm if l_score >= h_score else heuristic
        blended = max(h_score, l_score)
        return Classification(
            intent=winner.intent,
            confidence=blended,
            reasoning=winner.reasoning,
            source=f"merged:{self.name}",
        )


__all__ = ["HighestConfidenceMerge", "VotingMerge", "WeightedMerge"]
