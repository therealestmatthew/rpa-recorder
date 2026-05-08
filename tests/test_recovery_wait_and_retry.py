"""`WaitAndRetryStrategy` — pure-page pause unit tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from playwright.async_api import Error as PlaywrightError

from rpa_recorder.models import (
    ActionExecution,
    ActionType,
    ClickPayload,
    ElementSelector,
    ExecutionAttempt,
    ExecutionStatus,
    FailureMode,
    RecordedAction,
)
from rpa_recorder.recovery.protocol import RecoveryContext
from rpa_recorder.recovery.strategies.wait_and_retry import WaitAndRetryStrategy


class _FakePage:
    def __init__(self) -> None:
        self.waited_ms: list[int] = []

    async def wait_for_timeout(self, ms: int) -> None:
        self.waited_ms.append(ms)


def _click() -> RecordedAction:
    return RecordedAction(
        sequence=1,
        timestamp=datetime.now(UTC),
        action_type=ActionType.CLICK,
        payload=ClickPayload(),
        selector=ElementSelector(test_id="x"),
        url="https://example.com",
    )


def _failed(mode: FailureMode) -> ActionExecution:
    return ActionExecution(
        action_id=uuid4(),
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


async def test_wait_and_retry_pauses_and_returns_succeeded() -> None:
    page = _FakePage()
    strategy = WaitAndRetryStrategy(wait_ms=123)
    decision = await strategy.attempt(
        failed=_failed(FailureMode.TIMEOUT),
        page=page,  # type: ignore[arg-type]
        original=_click(),
        ctx=RecoveryContext(),
    )
    assert decision.applicable is True
    assert decision.succeeded is True
    assert page.waited_ms == [123]


def test_wait_and_retry_only_applies_to_relevant_modes() -> None:
    strategy = WaitAndRetryStrategy()
    assert FailureMode.TIMEOUT in strategy.applicable_modes
    assert FailureMode.ELEMENT_NOT_INTERACTABLE in strategy.applicable_modes
    assert FailureMode.ELEMENT_NOT_FOUND not in strategy.applicable_modes


async def test_wait_and_retry_handles_playwright_error_gracefully() -> None:
    class _Boom:
        async def wait_for_timeout(self, ms: int) -> None:
            raise PlaywrightError("nope")

    decision = await WaitAndRetryStrategy().attempt(
        failed=_failed(FailureMode.TIMEOUT),
        page=_Boom(),  # type: ignore[arg-type]
        original=_click(),
        ctx=RecoveryContext(),
    )
    assert decision.succeeded is False
    assert "wait failed" in decision.rationale
