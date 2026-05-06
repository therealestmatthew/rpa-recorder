"""`Classifier` — hybrid heuristic + LLM composition (the public M9 entry point).

`classify` runs the heuristic first; only when its confidence falls below
`threshold` is the LLM tier consulted. Results are merged by `MergeStrategy`.

`classify_batch` fans out via `asyncio.TaskGroup`. The per-task body
catches its own exceptions and converts them to UNKNOWN classifications,
so one bad action never aborts the batch (the TaskGroup default would
cancel siblings on the first raise).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import structlog

from rpa_recorder.classifier.heuristic.protocol import (
    Classification,
    ClassifyCandidate,
    RuleContext,
)
from rpa_recorder.models import SemanticIntent

from .merge import HighestConfidenceMerge

if TYPE_CHECKING:
    from rpa_recorder.classifier.heuristic import HeuristicEngine
    from rpa_recorder.models import RecordedAction

    from .classifier import LLMClassifier
    from .protocol import MergeStrategy

_log = structlog.get_logger(__name__)

_SURROUNDING_BEFORE: int = 2
_SURROUNDING_AFTER: int = 2


def _candidate_from(verdict: Classification) -> ClassifyCandidate:
    return ClassifyCandidate(
        intent=verdict.intent,
        confidence=verdict.confidence,
        reasoning=verdict.reasoning,
        source=verdict.source,
    )


class Classifier:
    """Composition of `HeuristicEngine` + `LLMClassifier`."""

    def __init__(
        self,
        *,
        heuristic: HeuristicEngine,
        llm: LLMClassifier,
        threshold: float = 0.7,
        merge: MergeStrategy | None = None,
    ) -> None:
        self._heuristic = heuristic
        self._llm = llm
        self._threshold = threshold
        self._merge: MergeStrategy = merge if merge is not None else HighestConfidenceMerge()

    async def classify(
        self,
        action: RecordedAction,
        surrounding: list[RecordedAction] | None = None,
    ) -> Classification:
        """Classify one action. Heuristic-first; LLM only on low confidence."""
        ctx_actions = list(surrounding) if surrounding else [action]
        try:
            index = ctx_actions.index(action)
        except ValueError:
            ctx_actions = [action, *ctx_actions]
            index = 0
        ctx = RuleContext(actions=ctx_actions, index=index)
        heuristic_verdict = self._heuristic.classify_pipeline.apply(action, ctx)

        if heuristic_verdict.confidence >= self._threshold:
            return Classification(
                intent=heuristic_verdict.intent,
                confidence=heuristic_verdict.confidence,
                reasoning=heuristic_verdict.reasoning,
                source=f"heuristic:{heuristic_verdict.source}",
            )

        llm_candidate = await self._llm.classify(action, ctx_actions)

        heuristic_candidate: ClassifyCandidate | None
        if (
            heuristic_verdict.intent is SemanticIntent.UNKNOWN
            and heuristic_verdict.confidence == 0.0
        ):
            heuristic_candidate = None
        else:
            heuristic_candidate = _candidate_from(heuristic_verdict)

        return self._merge.merge(heuristic=heuristic_candidate, llm=llm_candidate)

    async def classify_batch(self, actions: list[RecordedAction]) -> list[Classification]:
        """Classify a batch with structured concurrency. Per-action errors → UNKNOWN."""
        results: list[Classification | None] = [None] * len(actions)

        async def one(idx: int) -> None:
            action = actions[idx]
            start = max(0, idx - _SURROUNDING_BEFORE)
            end = min(len(actions), idx + _SURROUNDING_AFTER + 1)
            surrounding = actions[start:end]
            try:
                results[idx] = await self.classify(action, surrounding)
            except Exception as exc:
                _log.warning("classify_failed", action_id=str(action.id), error=str(exc))
                results[idx] = Classification(
                    intent=SemanticIntent.UNKNOWN,
                    confidence=0.0,
                    reasoning=f"classify failed: {exc}",
                    source="error",
                )

        async with asyncio.TaskGroup() as tg:
            for i in range(len(actions)):
                tg.create_task(one(i))

        # `results` is fully populated by the TaskGroup; cast away the Optional.
        return [r if r is not None else _unknown() for r in results]


def _unknown() -> Classification:
    return Classification(
        intent=SemanticIntent.UNKNOWN,
        confidence=0.0,
        reasoning="missing result",
        source="error",
    )


__all__ = ["Classifier"]
