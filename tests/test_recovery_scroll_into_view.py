"""`ScrollIntoViewStrategy` — fake-page unit tests."""

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
from rpa_recorder.recovery.strategies.scroll_into_view import ScrollIntoViewStrategy


class _FakeLocator:
    def __init__(
        self,
        *,
        count: int = 1,
        visible: bool = False,
    ) -> None:
        self._count = count
        self._visible = visible
        self.scrolled = 0

    async def count(self) -> int:
        return self._count

    async def is_visible(self) -> bool:
        return self._visible

    async def scroll_into_view_if_needed(self) -> None:
        self.scrolled += 1


class _FakePage:
    def __init__(self, locator: _FakeLocator) -> None:
        self._locator = locator

    def get_by_test_id(self, _: str) -> _FakeLocator:
        return self._locator

    @property
    def main_frame(self) -> Any:
        return self

    @property
    def frames(self) -> list[Any]:
        return [self]

    @property
    def url(self) -> str:
        return "https://example.com/main"


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
                failure_mode=FailureMode.ELEMENT_NOT_INTERACTABLE,
            )
        ],
    )


async def test_scroll_into_view_scrolls_offscreen_element() -> None:
    locator = _FakeLocator(count=1, visible=False)
    page = _FakePage(locator)
    decision = await ScrollIntoViewStrategy().attempt(
        failed=_failed(),
        page=page,  # type: ignore[arg-type]
        original=_click(ElementSelector(test_id="x")),
        ctx=RecoveryContext(),
    )
    assert decision.succeeded is True
    assert locator.scrolled == 1


async def test_scroll_into_view_already_visible_succeeds_trivially() -> None:
    locator = _FakeLocator(count=1, visible=True)
    page = _FakePage(locator)
    decision = await ScrollIntoViewStrategy().attempt(
        failed=_failed(),
        page=page,  # type: ignore[arg-type]
        original=_click(ElementSelector(test_id="x")),
        ctx=RecoveryContext(),
    )
    assert decision.succeeded is True
    assert "already visible" in decision.rationale
    assert locator.scrolled == 0


async def test_scroll_into_view_no_selector_is_inapplicable() -> None:
    page = _FakePage(_FakeLocator(count=0))
    decision = await ScrollIntoViewStrategy().attempt(
        failed=_failed(),
        page=page,  # type: ignore[arg-type]
        original=_click(None),
        ctx=RecoveryContext(),
    )
    assert decision.applicable is False
