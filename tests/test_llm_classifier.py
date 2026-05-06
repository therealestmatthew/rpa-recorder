"""`LLMClassifier` orchestrator tests."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

import pytest

from rpa_recorder.classifier.heuristic.protocol import ClassifyCandidate
from rpa_recorder.classifier.llm.cache import InMemoryResponseCache
from rpa_recorder.classifier.llm.classifier import LLMClassifier
from rpa_recorder.classifier.llm.cost import BudgetGuard
from rpa_recorder.classifier.llm.parsers.tool_use import ToolUseParser
from rpa_recorder.classifier.llm.prompts.classify_v1 import ClassifyV1Prompt
from rpa_recorder.classifier.llm.protocol import LLMBudgetExceeded, LLMResponse
from rpa_recorder.classifier.llm.retry import NoRetry
from rpa_recorder.models import (
    ActionType,
    ElementContext,
    InputPayload,
    RecordedAction,
    SemanticIntent,
)
from rpa_recorder.storage.db import LLMCallRow, create_engine, get_session, init_db

MakeActionFactory = Callable[..., RecordedAction]

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession


class _MockBackend:
    name: str = "mock"

    def __init__(
        self, *, model: str = "claude-sonnet-4-6", response: LLMResponse | None = None
    ) -> None:
        self.model = model
        self._response = response or LLMResponse(
            text=None,
            tool_calls=[
                {
                    "name": "classify",
                    "input": {"intent": "login", "confidence": 0.9, "reasoning": "stub"},
                }
            ],
            input_tokens=42,
            output_tokens=7,
            stop_reason="tool_use",
            raw={"id": "msg_test"},
        )
        self.calls: list[dict[str, Any]] = []

    async def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int,
        temperature: float = 0.0,
        timeout_s: float = 60.0,
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        self.calls.append(
            {
                "messages": messages,
                "max_tokens": max_tokens,
                "tools": tools,
                "timeout_s": timeout_s,
                "temperature": temperature,
            }
        )
        return self._response


def _password_action(make_action: MakeActionFactory) -> RecordedAction:
    return make_action(
        action_type=ActionType.INPUT,
        payload=InputPayload(value="x", is_sensitive=True),
        element_context=ElementContext(tag="input", attributes={"type": "password"}),
        url="https://example.com/login",
    )


@pytest.fixture
async def db_engine() -> AsyncIterator[AsyncEngine]:
    engine = create_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    yield engine
    await engine.dispose()


def _session_factory(engine: AsyncEngine) -> Any:
    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncSession]:
        async with get_session(engine) as session:
            yield session

    return factory


async def test_classify_returns_candidate(make_action: MakeActionFactory) -> None:
    action = _password_action(make_action)
    classifier = LLMClassifier(
        backend=_MockBackend(),
        prompt=ClassifyV1Prompt(),
        parser=ToolUseParser(),
        retry=NoRetry(),
        cache=None,
        max_concurrency=2,
    )
    candidate = await classifier.classify(action, [action])
    assert isinstance(candidate, ClassifyCandidate)
    assert candidate.intent is SemanticIntent.LOGIN
    assert candidate.confidence == 0.9


async def test_classify_cache_hit_skips_backend(make_action: MakeActionFactory) -> None:
    action = _password_action(make_action)
    backend = _MockBackend()
    cache = InMemoryResponseCache()
    classifier = LLMClassifier(
        backend=backend,
        prompt=ClassifyV1Prompt(),
        parser=ToolUseParser(),
        retry=NoRetry(),
        cache=cache,
    )
    # Prime cache with a synthetic response.
    primed = LLMResponse(
        text=None,
        tool_calls=[
            {
                "name": "classify",
                "input": {"intent": "search", "confidence": 0.7, "reasoning": "primed"},
            }
        ],
        input_tokens=1,
        output_tokens=1,
        stop_reason="tool_use",
        raw={},
    )
    key = classifier._cache_key(action, [action])
    await cache.set(key, primed, ttl_s=60)

    candidate = await classifier.classify(action, [action])
    assert candidate is not None
    assert candidate.intent is SemanticIntent.SEARCH
    assert backend.calls == []  # backend never invoked


async def test_classify_writes_silver_row(
    db_engine: AsyncEngine, make_action: MakeActionFactory
) -> None:
    action = _password_action(make_action)
    factory = _session_factory(db_engine)
    classifier = LLMClassifier(
        backend=_MockBackend(),
        prompt=ClassifyV1Prompt(),
        parser=ToolUseParser(),
        retry=NoRetry(),
        cache=None,
        session_factory=factory,
    )
    await classifier.classify(action, [action])

    async with get_session(db_engine) as db:
        from sqlalchemy import select  # noqa: PLC0415

        rows = (await db.execute(select(LLMCallRow))).scalars().all()
        assert len(rows) == 1
        row = rows[0]
        assert row.called_for == "classify"
        assert row.model == "claude-sonnet-4-6"
        assert row.input_tokens == 42
        assert row.output_tokens == 7
        assert row.action_id == str(action.id)
        assert row.latency_ms >= 0


async def test_classify_writes_bronze_blob(make_action: MakeActionFactory) -> None:
    action = _password_action(make_action)
    bronze_calls: list[dict[str, Any]] = []

    class _BronzeStub:
        async def write_llm_call(self, call_id: Any, payload: Any) -> str:
            bronze_calls.append({"call_id": call_id, "payload": payload})
            return f"llm/{call_id}.json"

    classifier = LLMClassifier(
        backend=_MockBackend(),
        prompt=ClassifyV1Prompt(),
        parser=ToolUseParser(),
        retry=NoRetry(),
        cache=None,
        bronze=_BronzeStub(),  # type: ignore[arg-type]
    )
    await classifier.classify(action, [action])
    assert len(bronze_calls) == 1
    assert "prompt" in bronze_calls[0]["payload"]
    assert "response" in bronze_calls[0]["payload"]


async def test_classify_returns_none_on_parse_failure(make_action: MakeActionFactory) -> None:
    action = _password_action(make_action)

    class _NoneParser:
        name = "none"

        def parse(self, response: Any) -> None:
            return None

    classifier = LLMClassifier(
        backend=_MockBackend(),
        prompt=ClassifyV1Prompt(),
        parser=_NoneParser(),
        retry=NoRetry(),
        cache=None,
    )
    candidate = await classifier.classify(action, [action])
    assert candidate is None


async def test_classify_respects_budget_guard(make_action: MakeActionFactory) -> None:
    action = _password_action(make_action)
    guard = BudgetGuard(daily_budget_usd=0.0001)
    await guard.record_spend(0.01)
    backend = _MockBackend()
    classifier = LLMClassifier(
        backend=backend,
        prompt=ClassifyV1Prompt(),
        parser=ToolUseParser(),
        retry=NoRetry(),
        cache=None,
        budget=guard,
    )
    with pytest.raises(LLMBudgetExceeded):
        await classifier.classify(action, [action])
    assert backend.calls == []


async def test_classify_partial_persistence_failure_does_not_raise(
    make_action: MakeActionFactory,
) -> None:
    action = _password_action(make_action)

    class _FailingBronze:
        async def write_llm_call(self, call_id: Any, payload: Any) -> str:
            raise RuntimeError("bronze down")

    classifier = LLMClassifier(
        backend=_MockBackend(),
        prompt=ClassifyV1Prompt(),
        parser=ToolUseParser(),
        retry=NoRetry(),
        cache=InMemoryResponseCache(),
        bronze=_FailingBronze(),  # type: ignore[arg-type]
    )
    # Must not raise; bronze failure is logged and swallowed.
    candidate = await classifier.classify(action, [action])
    assert candidate is not None


def test_default_classifier_factory_wires_components() -> None:
    """`default_classifier()` constructs a hybrid `Classifier` without touching the network."""
    from rpa_recorder.classifier.llm import Classifier as HybridClassifier  # noqa: PLC0415
    from rpa_recorder.classifier.llm import default_classifier  # noqa: PLC0415

    class _DummyClient:
        class messages:  # noqa: N801
            @staticmethod
            async def create(**_: Any) -> Any:  # pragma: no cover - never called
                raise AssertionError("default_classifier must not call the API")

    classifier = default_classifier(anthropic_client=_DummyClient())
    assert isinstance(classifier, HybridClassifier)


async def test_classify_caches_response_after_call(make_action: MakeActionFactory) -> None:
    action = _password_action(make_action)
    cache = InMemoryResponseCache()
    backend = _MockBackend()
    classifier = LLMClassifier(
        backend=backend,
        prompt=ClassifyV1Prompt(),
        parser=ToolUseParser(),
        retry=NoRetry(),
        cache=cache,
    )
    await classifier.classify(action, [action])
    await classifier.classify(action, [action])
    # Second call should hit the cache.
    assert len(backend.calls) == 1
