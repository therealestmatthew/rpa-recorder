"""`FrameSwitchStrategy` — fake-page iframe walk unit tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

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
from rpa_recorder.recovery.strategies.frame_switch import FrameSwitchStrategy


class _FakeLocator:
    def __init__(self, *, count: int) -> None:
        self._count = count

    async def count(self) -> int:
        return self._count


class _FakeFrame:
    def __init__(self, *, url: str, count: int = 1) -> None:
        self.url = url
        self._count = count

    def get_by_test_id(self, _: str) -> _FakeLocator:
        return _FakeLocator(count=self._count)

    def get_by_role(self, *_args: Any, **_kwargs: Any) -> _FakeLocator:
        return _FakeLocator(count=0)

    def get_by_text(self, *_args: Any, **_kwargs: Any) -> _FakeLocator:
        return _FakeLocator(count=0)

    def locator(self, *_args: Any, **_kwargs: Any) -> _FakeLocator:
        return _FakeLocator(count=0)


class _FakePage:
    def __init__(self, frames: list[_FakeFrame]) -> None:
        self._main = _FakeFrame(url="https://example.com/main", count=0)
        self._all = [self._main, *frames]

    @property
    def main_frame(self) -> _FakeFrame:
        return self._main

    @property
    def frames(self) -> list[_FakeFrame]:
        return self._all


def _click(selector: ElementSelector | None) -> RecordedAction:
    return RecordedAction(
        sequence=1,
        timestamp=datetime.now(UTC),
        action_type=ActionType.CLICK,
        payload=ClickPayload(),
        selector=selector,
        url="https://example.com",
    )


def _failed() -> ActionExecution:
    return ActionExecution(
        action_id=uuid4(),
        status=ExecutionStatus.FAILED,
        attempts=[
            ExecutionAttempt(
                attempt_number=1,
                started_at=datetime.now(UTC),
                ended_at=datetime.now(UTC),
                status=ExecutionStatus.FAILED,
                failure_mode=FailureMode.ELEMENT_NOT_FOUND,
            )
        ],
    )


async def test_frame_switch_locates_inside_iframe() -> None:
    frame = _FakeFrame(url="https://embed.example.com/inner", count=1)
    page = _FakePage([frame])
    decision = await FrameSwitchStrategy().attempt(
        failed=_failed(),
        page=page,  # type: ignore[arg-type]
        original=_click(ElementSelector(test_id="inner")),
        ctx=RecoveryContext(),
    )
    assert decision.succeeded is True
    assert decision.new_selector is not None
    assert decision.new_selector.frame_url == "https://embed.example.com/inner"


async def test_frame_switch_no_iframes_returns_failure() -> None:
    page = _FakePage([])
    decision = await FrameSwitchStrategy().attempt(
        failed=_failed(),
        page=page,  # type: ignore[arg-type]
        original=_click(ElementSelector(test_id="x")),
        ctx=RecoveryContext(),
    )
    assert decision.applicable is True
    assert decision.succeeded is False
    assert "no iframes" in decision.rationale


async def test_frame_switch_no_match_returns_failure() -> None:
    frame = _FakeFrame(url="https://embed.example.com/inner", count=0)
    page = _FakePage([frame])
    decision = await FrameSwitchStrategy().attempt(
        failed=_failed(),
        page=page,  # type: ignore[arg-type]
        original=_click(ElementSelector(test_id="x")),
        ctx=RecoveryContext(),
    )
    assert decision.applicable is True
    assert decision.succeeded is False


async def test_frame_switch_no_selector_is_inapplicable() -> None:
    page = _FakePage([_FakeFrame(url="https://x", count=1)])
    decision = await FrameSwitchStrategy().attempt(
        failed=_failed(),
        page=page,  # type: ignore[arg-type]
        original=_click(None),
        ctx=RecoveryContext(),
    )
    assert decision.applicable is False
