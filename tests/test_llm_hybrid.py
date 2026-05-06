"""Hybrid `Classifier` (heuristic + LLM)."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from rpa_recorder.classifier.heuristic import default_pipeline
from rpa_recorder.classifier.llm.classifier import LLMClassifier
from rpa_recorder.classifier.llm.hybrid import Classifier
from rpa_recorder.classifier.llm.merge import HighestConfidenceMerge
from rpa_recorder.classifier.llm.parsers.tool_use import ToolUseParser
from rpa_recorder.classifier.llm.prompts.classify_v1 import ClassifyV1Prompt
from rpa_recorder.classifier.llm.protocol import LLMResponse
from rpa_recorder.classifier.llm.retry import NoRetry
from rpa_recorder.models import (
    ActionType,
    ClickPayload,
    ElementContext,
    InputPayload,
    RecordedAction,
    SemanticIntent,
)

MakeActionFactory = Callable[..., RecordedAction]

if TYPE_CHECKING:
    from rpa_recorder.classifier.llm.protocol import LLMBackend


class _CountingBackend:
    name: str = "count"
    model: str = "claude-sonnet-4-6"

    def __init__(self, *, intent: str = "search", confidence: float = 0.9) -> None:
        self._intent = intent
        self._confidence = confidence
        self.call_count: int = 0

    async def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int,
        temperature: float = 0.0,
        timeout_s: float = 60.0,
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        self.call_count += 1
        return LLMResponse(
            text=None,
            tool_calls=[
                {
                    "name": "classify",
                    "input": {
                        "intent": self._intent,
                        "confidence": self._confidence,
                        "reasoning": "stub",
                    },
                }
            ],
            input_tokens=1,
            output_tokens=1,
            stop_reason="tool_use",
            raw={},
        )


def _llm(backend: LLMBackend) -> LLMClassifier:
    return LLMClassifier(
        backend=backend,
        prompt=ClassifyV1Prompt(),
        parser=ToolUseParser(),
        retry=NoRetry(),
        cache=None,
        max_concurrency=4,
    )


def _password_action(make_action: MakeActionFactory) -> RecordedAction:
    return make_action(
        action_type=ActionType.INPUT,
        payload=InputPayload(value="x", is_sensitive=True),
        element_context=ElementContext(tag="input", attributes={"type": "password"}),
        url="https://example.com/login",
    )


def _bare_click(make_action: MakeActionFactory) -> RecordedAction:
    return make_action(
        action_type=ActionType.CLICK,
        payload=ClickPayload(),
        element_context=ElementContext(tag="div", attributes={}),
    )


async def test_hybrid_skips_llm_when_heuristic_confident(make_action: MakeActionFactory) -> None:
    backend = _CountingBackend()
    classifier = Classifier(
        heuristic=default_pipeline(),
        llm=_llm(backend),
        threshold=0.7,
        merge=HighestConfidenceMerge(),
    )
    verdict = await classifier.classify(_password_action(make_action))
    assert verdict.intent is SemanticIntent.LOGIN
    assert backend.call_count == 0


async def test_hybrid_calls_llm_when_heuristic_uncertain(make_action: MakeActionFactory) -> None:
    backend = _CountingBackend(intent="navigation", confidence=0.85)
    classifier = Classifier(
        heuristic=default_pipeline(),
        llm=_llm(backend),
        threshold=0.7,
        merge=HighestConfidenceMerge(),
    )
    verdict = await classifier.classify(_bare_click(make_action))
    assert backend.call_count == 1
    assert verdict.intent is SemanticIntent.NAVIGATION


async def test_hybrid_threshold_can_force_llm_for_high_heuristic(
    make_action: MakeActionFactory,
) -> None:
    backend = _CountingBackend(intent="search", confidence=0.99)
    classifier = Classifier(
        heuristic=default_pipeline(),
        llm=_llm(backend),
        threshold=0.99,  # heuristic 0.95 (password) is now below cutoff
        merge=HighestConfidenceMerge(),
    )
    await classifier.classify(_password_action(make_action))
    assert backend.call_count == 1


async def test_classify_batch_runs_concurrently(make_action: MakeActionFactory) -> None:
    backend = _CountingBackend(intent="search", confidence=0.9)
    classifier = Classifier(
        heuristic=default_pipeline(),
        llm=_llm(backend),
        threshold=0.7,
        merge=HighestConfidenceMerge(),
    )
    actions = [_bare_click(make_action) for _ in range(5)]
    results = await classifier.classify_batch(actions)
    assert len(results) == 5
    assert all(r.intent is SemanticIntent.SEARCH for r in results)
    assert backend.call_count == 5


async def test_classify_batch_isolates_failures(make_action: MakeActionFactory) -> None:
    actions = [_bare_click(make_action) for _ in range(3)]
    target_id = actions[1].id

    class _SometimesBackend:
        name = "fail"
        model = "claude-sonnet-4-6"

        async def complete(self, messages: list[dict[str, Any]], **kwargs: Any) -> LLMResponse:
            # Fail for the middle action by reading prompt body.
            if str(target_id) in messages[0]["content"]:
                raise RuntimeError("boom")
            return LLMResponse(
                text=None,
                tool_calls=[
                    {
                        "name": "classify",
                        "input": {"intent": "search", "confidence": 0.9, "reasoning": "ok"},
                    }
                ],
                input_tokens=1,
                output_tokens=1,
                stop_reason="tool_use",
                raw={},
            )

    classifier = Classifier(
        heuristic=default_pipeline(),
        llm=LLMClassifier(
            backend=_SometimesBackend(),
            prompt=ClassifyV1Prompt(),
            parser=ToolUseParser(),
            retry=NoRetry(),
            cache=None,
        ),
        threshold=0.7,
        merge=HighestConfidenceMerge(),
    )
    # The prompt builder doesn't include action.id, so we need to surface
    # the failure another way — patch the LLM classifier directly.

    original_classify = classifier._llm.classify
    targeted = actions[1]

    async def maybe_fail(action: RecordedAction, surrounding: list[RecordedAction]) -> Any:
        if action.id == targeted.id:
            raise RuntimeError("targeted")
        return await original_classify(action, surrounding)

    classifier._llm.classify = maybe_fail  # type: ignore[method-assign]

    results = await classifier.classify_batch(actions)
    assert len(results) == 3
    assert results[1].intent is SemanticIntent.UNKNOWN
    assert results[1].source == "error"
    # Other actions still classified successfully via the LLM tier.
    assert results[0].intent is SemanticIntent.SEARCH
    assert results[2].intent is SemanticIntent.SEARCH


async def test_hybrid_uses_default_merge_when_omitted(make_action: MakeActionFactory) -> None:
    backend = _CountingBackend(intent="search", confidence=0.9)
    classifier = Classifier(
        heuristic=default_pipeline(),
        llm=_llm(backend),
        threshold=0.7,
    )
    verdict = await classifier.classify(_bare_click(make_action))
    # HighestConfidenceMerge default; LLM 0.9 wins over heuristic 0.0.
    assert verdict.intent is SemanticIntent.SEARCH
