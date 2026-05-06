"""Modular LLM classifier — Anthropic-backed default with pluggable backends.

Eight swappable concerns: backend, prompt, parser, retry, merge (the five
listed by the bootstrap spec) plus cache, semaphore-based concurrency, and
budget guard. The hybrid `Classifier` composes M7's `HeuristicEngine` with
the LLM tier — heuristic first, LLM only when confidence < threshold.

Public API:

    from rpa_recorder.classifier.llm import default_classifier
    classifier = default_classifier()
    verdict = await classifier.classify(action, surrounding)
"""

from typing import TYPE_CHECKING

from .backends.anthropic import AnthropicBackend
from .cache import InMemoryResponseCache, RedisResponseCache
from .classifier import LLMClassifier
from .cost import BudgetGuard
from .hybrid import Classifier
from .merge import HighestConfidenceMerge, VotingMerge, WeightedMerge
from .parsers.tool_use import ToolUseParser
from .prompts.classify_v1 import ClassifyV1Prompt
from .protocol import (
    LLMBackend,
    LLMBudgetExceeded,
    LLMResponse,
    MergeStrategy,
    PromptStrategy,
    ResponseCache,
    ResponseParser,
    RetryPolicy,
)
from .retry import ExponentialBackoffRetry, NoRetry

if TYPE_CHECKING:
    from collections.abc import Callable
    from contextlib import AbstractAsyncContextManager
    from typing import Any

    from sqlalchemy.ext.asyncio import AsyncSession

    from rpa_recorder.classifier.heuristic import HeuristicEngine
    from rpa_recorder.medallion import BronzeWriter


def default_classifier(
    *,
    redis: object | None = None,
    heuristic: HeuristicEngine | None = None,
    bronze: BronzeWriter | None = None,
    session_factory: Callable[[], AbstractAsyncContextManager[AsyncSession]] | None = None,
    anthropic_client: Any | None = None,
    threshold: float | None = None,
) -> Classifier:
    """Curated defaults: Anthropic backend, classify_v1 prompt, tool-use parser,
    exponential backoff retry, Redis cache (or in-memory if `redis` is None),
    highest-confidence merge.

    Pass `redis=` to use `RedisResponseCache` + a Redis-backed `BudgetGuard`.
    Without it, both fall back to per-process in-memory implementations and
    log a single warning so callers know the budget is not distributed.
    """
    from rpa_recorder.classifier.heuristic import default_pipeline  # noqa: PLC0415
    from rpa_recorder.config import Config  # noqa: PLC0415

    cfg = Config()
    backend = AnthropicBackend(model=cfg.llm_model, client=anthropic_client)
    cache: ResponseCache = (
        RedisResponseCache(redis) if redis is not None else InMemoryResponseCache()
    )
    budget = BudgetGuard(redis=redis, daily_budget_usd=cfg.llm_daily_budget_usd)

    llm = LLMClassifier(
        backend=backend,
        prompt=ClassifyV1Prompt(),
        parser=ToolUseParser(),
        retry=ExponentialBackoffRetry(max_attempts=3),
        cache=cache,
        cache_ttl_s=cfg.llm_cache_ttl_s,
        bronze=bronze,
        session_factory=session_factory,
        budget=budget,
        request_timeout_s=cfg.llm_request_timeout_s,
        max_concurrency=cfg.llm_max_concurrency,
    )

    return Classifier(
        heuristic=heuristic if heuristic is not None else default_pipeline(),
        llm=llm,
        threshold=threshold if threshold is not None else cfg.classifier_confidence_threshold,
        merge=HighestConfidenceMerge(),
    )


__all__ = [
    "AnthropicBackend",
    "BudgetGuard",
    "Classifier",
    "ClassifyV1Prompt",
    "ExponentialBackoffRetry",
    "HighestConfidenceMerge",
    "InMemoryResponseCache",
    "LLMBackend",
    "LLMBudgetExceeded",
    "LLMClassifier",
    "LLMResponse",
    "MergeStrategy",
    "NoRetry",
    "PromptStrategy",
    "RedisResponseCache",
    "ResponseCache",
    "ResponseParser",
    "RetryPolicy",
    "ToolUseParser",
    "VotingMerge",
    "WeightedMerge",
    "default_classifier",
]
