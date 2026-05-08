# mypy: disable-error-code="no-untyped-def, no-untyped-call, type-arg, unused-ignore, attr-defined, comparison-overlap, misc"
"""Unit tests for the `event_emitter` hook on `Executor` (M12).

Mocks the Playwright Page so the test stays in-process — full browser-driven
emission is exercised by the integration tests in `test_executor.py` once
they're wired with an emitter.
"""

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from rpa_recorder.browser.executor import Executor
from rpa_recorder.models import (
    ActionType,
    ExecutionStatus,
    NavigatePayload,
    RecordedAction,
    Recording,
)


def _navigate_recording(url: str = "about:blank") -> Recording:
    return Recording(
        name="emitter-fixture",
        created_at=datetime.now(UTC),
        starting_url=url,
        actions=[
            RecordedAction(
                sequence=1,
                timestamp=datetime.now(UTC),
                action_type=ActionType.NAVIGATE,
                payload=NavigatePayload(url=url),
                selector=None,
                url=url,
            )
        ],
    )


def _no_selector_recording() -> Recording:
    """A CLICK action with no selector — forces SelectorResolutionError."""
    return Recording(
        name="emitter-fixture-fail",
        created_at=datetime.now(UTC),
        starting_url="about:blank",
        actions=[
            RecordedAction(
                sequence=1,
                timestamp=datetime.now(UTC),
                action_type=ActionType.CLICK,
                payload={},
                selector=None,
                url="about:blank",
            )
        ],
    )


def _fake_page() -> MagicMock:
    page = MagicMock()
    page.on = MagicMock()
    page.goto = AsyncMock(return_value=None)
    page.screenshot = AsyncMock(return_value=b"\x89PNG")
    page.content = AsyncMock(return_value="<html></html>")
    page.accessibility = MagicMock()
    page.accessibility.snapshot = AsyncMock(return_value={"name": "root"})
    return page


@pytest.mark.asyncio
async def test_executor_emits_run_and_action_lifecycle_on_success(tmp_path):
    events: list[tuple[str, dict[str, Any]]] = []

    async def emitter(event_type: str, payload: dict[str, Any]) -> None:
        events.append((event_type, payload))

    page = _fake_page()
    recording = _navigate_recording()
    executor = Executor(
        page,  # type: ignore[arg-type]
        recording,
        screenshots_dir=tmp_path / "ss",
        dom_dir=tmp_path / "dom",
        event_emitter=emitter,
    )
    result = await executor.run()

    assert result.status == ExecutionStatus.SUCCESS
    types = [t for t, _ in events]
    assert types == ["run_started", "action_started", "action_succeeded", "run_finished"]

    started = events[0][1]
    assert started["recording_id"] == str(recording.id)
    assert started["n_actions"] == 1

    finished = events[-1][1]
    assert finished["status"] == ExecutionStatus.SUCCESS.value
    assert finished["n_succeeded"] == 1
    assert finished["n_failed"] == 0


@pytest.mark.asyncio
async def test_executor_emits_action_failed_on_terminal_failure(tmp_path):
    events: list[tuple[str, dict[str, Any]]] = []

    async def emitter(event_type: str, payload: dict[str, Any]) -> None:
        events.append((event_type, payload))

    page = _fake_page()
    recording = _no_selector_recording()
    executor = Executor(
        page,  # type: ignore[arg-type]
        recording,
        screenshots_dir=tmp_path / "ss",
        dom_dir=tmp_path / "dom",
        event_emitter=emitter,
    )
    result = await executor.run()

    assert result.status == ExecutionStatus.FAILED
    types = [t for t, _ in events]
    assert "action_failed" in types
    failed_payload = next(p for t, p in events if t == "action_failed")
    assert "failure_mode" in failed_payload
    assert failed_payload["error"]


@pytest.mark.asyncio
async def test_executor_swallows_emitter_exceptions(tmp_path):
    async def broken_emitter(event_type: str, payload: dict[str, Any]) -> None:
        raise RuntimeError("emitter exploded")

    page = _fake_page()
    recording = _navigate_recording()
    executor = Executor(
        page,  # type: ignore[arg-type]
        recording,
        screenshots_dir=tmp_path / "ss",
        dom_dir=tmp_path / "dom",
        event_emitter=broken_emitter,
    )
    # Must complete cleanly even though every emit raises.
    result = await executor.run()
    assert result.status == ExecutionStatus.SUCCESS


@pytest.mark.asyncio
async def test_executor_supports_sync_emitter(tmp_path):
    events: list[str] = []

    def sync_emitter(event_type: str, _payload: dict[str, Any]) -> None:
        events.append(event_type)

    page = _fake_page()
    recording = _navigate_recording()
    executor = Executor(
        page,  # type: ignore[arg-type]
        recording,
        screenshots_dir=tmp_path / "ss",
        dom_dir=tmp_path / "dom",
        event_emitter=sync_emitter,
    )
    await executor.run()
    assert "run_started" in events
    assert "run_finished" in events
