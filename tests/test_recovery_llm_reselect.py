"""`LLMReselectStrategy` — unit tests with a mock backend + cache + budget."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from rpa_recorder.classifier.llm.cache import InMemoryResponseCache
from rpa_recorder.classifier.llm.cost import BudgetGuard
from rpa_recorder.classifier.llm.protocol import LLMResponse
from rpa_recorder.classifier.llm.retry import NoRetry
from rpa_recorder.models import (
    ActionExecution,
    ActionType,
    ClickPayload,
    ElementSelector,
    ExecutionAttempt,
    ExecutionStatus,
    FailureMode,
    InputPayload,
    RecordedAction,
)
from rpa_recorder.recovery.prompts.reselect_v1 import ReselectV1Prompt
from rpa_recorder.recovery.protocol import RecoveryContext
from rpa_recorder.recovery.strategies.llm_reselect import (
    LLMReselectStrategy,
    filter_dom,
)


class _FakePage:
    def __init__(
        self, html: str = "<html><body><button data-testid='real'>Hi</button></body></html>"
    ) -> None:
        self._html = html

    async def content(self) -> str:
        return self._html


class _MockBackend:
    name: str = "mock"
    model: str = "claude-sonnet-4-6"

    def __init__(self, response: LLMResponse) -> None:
        self._response = response
        self.calls = 0

    async def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int,
        temperature: float = 0.0,
        timeout_s: float = 60.0,
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        self.calls += 1
        return self._response


def _reselect_response(*, sel: dict[str, Any]) -> LLMResponse:
    args = {"rationale": "found a fresh target", **sel}
    return LLMResponse(
        text=None,
        tool_calls=[{"name": "reselect", "input": args}],
        input_tokens=10,
        output_tokens=5,
        stop_reason="tool_use",
        raw={"id": "msg_test"},
    )


def _click_action() -> RecordedAction:
    return RecordedAction(
        sequence=1,
        timestamp=datetime.now(UTC),
        action_type=ActionType.CLICK,
        payload=ClickPayload(),
        selector=ElementSelector(test_id="stale"),
        url="https://example.com",
        page_title="Example",
    )


def _failed_view(action: RecordedAction, mode: FailureMode) -> ActionExecution:
    return ActionExecution(
        action_id=action.id,
        status=ExecutionStatus.FAILED,
        attempts=[
            ExecutionAttempt(
                attempt_number=1,
                started_at=datetime.now(UTC),
                ended_at=datetime.now(UTC),
                status=ExecutionStatus.FAILED,
                failure_mode=mode,
            )
        ],
    )


async def test_llm_reselect_returns_new_selector_from_tool_use() -> None:
    backend = _MockBackend(_reselect_response(sel={"test_id": "real"}))
    ctx = RecoveryContext(
        llm_backend=backend,
        llm_retry=NoRetry(),
    )
    action = _click_action()
    decision = await LLMReselectStrategy().attempt(
        failed=_failed_view(action, FailureMode.ELEMENT_NOT_FOUND),
        page=_FakePage(),  # type: ignore[arg-type]
        original=action,
        ctx=ctx,
    )
    assert decision.applicable is True
    assert decision.succeeded is True
    assert decision.new_selector is not None
    assert decision.new_selector.test_id == "real"
    assert backend.calls == 1


async def test_llm_reselect_caches_response() -> None:
    backend = _MockBackend(_reselect_response(sel={"test_id": "real"}))
    cache = InMemoryResponseCache()
    ctx = RecoveryContext(
        llm_backend=backend,
        llm_retry=NoRetry(),
        llm_cache=cache,
    )
    action = _click_action()
    page = _FakePage()
    s = LLMReselectStrategy()
    first = await s.attempt(
        failed=_failed_view(action, FailureMode.ELEMENT_NOT_FOUND),
        page=page,  # type: ignore[arg-type]
        original=action,
        ctx=ctx,
    )
    second = await s.attempt(
        failed=_failed_view(action, FailureMode.ELEMENT_NOT_FOUND),
        page=page,  # type: ignore[arg-type]
        original=action,
        ctx=ctx,
    )
    assert first.succeeded is True
    assert second.succeeded is True
    assert backend.calls == 1  # second call hit cache


async def test_llm_reselect_respects_budget_guard() -> None:
    backend = _MockBackend(_reselect_response(sel={"test_id": "real"}))
    budget = BudgetGuard(daily_budget_usd=0.0)  # already exceeded
    ctx = RecoveryContext(
        llm_backend=backend,
        llm_retry=NoRetry(),
        budget=budget,
    )
    action = _click_action()
    decision = await LLMReselectStrategy().attempt(
        failed=_failed_view(action, FailureMode.ELEMENT_NOT_FOUND),
        page=_FakePage(),  # type: ignore[arg-type]
        original=action,
        ctx=ctx,
    )
    assert decision.applicable is True
    assert decision.succeeded is False
    assert "budget exceeded" in decision.rationale
    assert backend.calls == 0


async def test_llm_reselect_short_circuits_without_backend() -> None:
    action = _click_action()
    decision = await LLMReselectStrategy().attempt(
        failed=_failed_view(action, FailureMode.ELEMENT_NOT_FOUND),
        page=_FakePage(),  # type: ignore[arg-type]
        original=action,
        ctx=RecoveryContext(),
    )
    assert decision.applicable is False


async def test_llm_reselect_parser_abstain_returns_failure() -> None:
    # Empty tool call — parser will return None.
    response = LLMResponse(
        text=None,
        tool_calls=[{"name": "reselect", "input": {"rationale": "i give up"}}],
        input_tokens=0,
        output_tokens=0,
        stop_reason="tool_use",
        raw={},
    )
    backend = _MockBackend(response)
    ctx = RecoveryContext(llm_backend=backend, llm_retry=NoRetry())
    action = _click_action()
    decision = await LLMReselectStrategy().attempt(
        failed=_failed_view(action, FailureMode.ELEMENT_NOT_FOUND),
        page=_FakePage(),  # type: ignore[arg-type]
        original=action,
        ctx=ctx,
    )
    assert decision.applicable is True
    assert decision.succeeded is False
    assert "abstained" in decision.rationale


def test_filter_dom_strips_noise() -> None:
    raw = (
        "<html><head><style>body{}</style></head>"
        "<body><svg><path/></svg><!-- comment -->"
        "<div>visible content</div>"
        "<script>const x = 1;</script></body></html>"
    )
    out = filter_dom(raw)
    assert "<style>" not in out
    assert "<svg>" not in out
    assert "comment" not in out
    assert "<script>" not in out
    assert "visible content" in out


def test_filter_dom_truncates_to_budget() -> None:
    raw = "<div>" + ("x" * 20_000) + "</div>"
    out = filter_dom(raw, budget_bytes=200)
    assert len(out.encode("utf-8")) <= 200


@pytest.mark.parametrize(
    "value",
    ["passw0rd!", "secret-token-xyz"],
)
def test_redacts_sensitive_payload_in_prompt_body(value: str) -> None:
    action = RecordedAction(
        sequence=1,
        timestamp=datetime.now(UTC),
        action_type=ActionType.INPUT,
        payload=InputPayload(value=value, is_sensitive=True),
        selector=ElementSelector(test_id="pwd"),
        url="https://example.com",
    )
    messages, _ = ReselectV1Prompt().build(action, "<html></html>", FailureMode.ELEMENT_NOT_FOUND)
    body = messages[0]["content"]
    assert value not in body
