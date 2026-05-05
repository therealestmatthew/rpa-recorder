"""Shared pytest fixtures.

Currently exposes a `make_action` factory used by the heuristic-classifier tests
to build small `RecordedAction` instances without browser involvement.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from rpa_recorder.models import (
    ActionType,
    ClickPayload,
    ElementContext,
    ElementSelector,
    InputPayload,
    NavigatePayload,
    RecordedAction,
)

_BASE_TS = datetime(2026, 5, 4, 12, 0, 0, tzinfo=UTC)


MakeActionFactory = Callable[..., RecordedAction]


@pytest.fixture
def make_action() -> MakeActionFactory:
    """Factory: build a `RecordedAction` with sensible defaults per action_type.

    `offset_ms` is added to a fixed base timestamp so callers can express
    millisecond-level temporal relationships (used by the focus-blur and
    coalesce tests).
    """

    def _factory(
        sequence: int = 0,
        *,
        action_type: ActionType = ActionType.CLICK,
        offset_ms: int = 0,
        payload: Any = None,
        selector: ElementSelector | None = None,
        element_context: ElementContext | None = None,
        url: str = "https://example.com",
    ) -> RecordedAction:
        if payload is None:
            if action_type is ActionType.CLICK:
                payload = ClickPayload()
            elif action_type is ActionType.INPUT:
                payload = InputPayload(value="x")
            elif action_type is ActionType.NAVIGATE:
                payload = NavigatePayload(url="https://example.com")
            else:
                payload = {}
        return RecordedAction(
            sequence=sequence,
            timestamp=_BASE_TS + timedelta(milliseconds=offset_ms),
            action_type=action_type,
            payload=payload,
            selector=selector,
            element_context=element_context,
            url=url,
        )

    return _factory
