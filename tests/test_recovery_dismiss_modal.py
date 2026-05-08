"""`DismissModalStrategy` — fake-page click unit tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest
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
from rpa_recorder.recovery.strategies.dismiss_modal import DismissModalStrategy


class _FakeLocator:
    def __init__(self, *, count: int, click_raises: BaseException | None = None) -> None:
        self._count = count
        self._click_raises = click_raises
        self.clicked = 0

    @property
    def first(self) -> _FakeLocator:
        return self

    async def count(self) -> int:
        return self._count

    async def click(self, *, timeout: int) -> None:  # noqa: ASYNC109
        # `timeout` mirrors Playwright's locator.click signature; not a real async timeout.
        _ = timeout
        self.clicked += 1
        if self._click_raises is not None:
            raise self._click_raises


class _FakePage:
    def __init__(self, locator: _FakeLocator) -> None:
        self._locator = locator

    def locator(self, _selector: str) -> _FakeLocator:
        return self._locator


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


async def test_dismiss_modal_clicks_close_button() -> None:
    locator = _FakeLocator(count=1)
    page = _FakePage(locator)
    decision = await DismissModalStrategy().attempt(
        failed=_failed(FailureMode.UNEXPECTED_MODAL),
        page=page,  # type: ignore[arg-type]
        original=_click(),
        ctx=RecoveryContext(),
    )
    assert decision.applicable is True
    assert decision.succeeded is True
    assert locator.clicked == 1


async def test_dismiss_modal_no_dialog_returns_failure() -> None:
    page = _FakePage(_FakeLocator(count=0))
    decision = await DismissModalStrategy().attempt(
        failed=_failed(FailureMode.UNEXPECTED_MODAL),
        page=page,  # type: ignore[arg-type]
        original=_click(),
        ctx=RecoveryContext(),
    )
    assert decision.applicable is True
    assert decision.succeeded is False
    assert "no dialog close" in decision.rationale


@pytest.mark.parametrize(
    "exc",
    [TimeoutError(), PlaywrightError("blocked")],
)
async def test_dismiss_modal_swallows_click_failure(exc: BaseException) -> None:
    _ = asyncio  # keep the import live in case future cases need it
    locator = _FakeLocator(count=1, click_raises=exc)
    page = _FakePage(locator)
    decision = await DismissModalStrategy().attempt(
        failed=_failed(FailureMode.UNEXPECTED_MODAL),
        page=page,  # type: ignore[arg-type]
        original=_click(),
        ctx=RecoveryContext(),
    )
    assert decision.succeeded is False
    assert "close click failed" in decision.rationale


def test_dismiss_modal_modes() -> None:
    s = DismissModalStrategy()
    assert FailureMode.ELEMENT_NOT_INTERACTABLE in s.applicable_modes
    assert FailureMode.UNEXPECTED_MODAL in s.applicable_modes
    assert FailureMode.ELEMENT_NOT_FOUND not in s.applicable_modes
