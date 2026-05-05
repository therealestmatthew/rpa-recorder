"""Integration tests for `Executor` against a static HTML fixture."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from rpa_recorder.browser.executor import Executor, SelectorResolutionError
from rpa_recorder.browser.session import BrowserSession
from rpa_recorder.models import (
    ActionType,
    ClickPayload,
    ElementSelector,
    ExecutionStatus,
    FailureMode,
    InputPayload,
    RecordedAction,
    Recording,
)

_FIXTURE_HTML = """<!doctype html>
<html lang="en">
  <head><title>Executor fixture</title></head>
  <body>
    <form id="login-form">
      <label for="email">Email</label>
      <input id="email" name="email" type="email" data-testid="email-field" />

      <label for="password">Password</label>
      <input id="password" name="password" type="password" />

      <button id="save" data-testid="save-btn" aria-label="Save" type="button">
        Save
      </button>

      <div id="duplicate-target">
        <span class="dup">First</span>
        <span class="dup">Second</span>
      </div>
    </form>

    <script>
      window.__clicked = false;
      document.getElementById("save").addEventListener(
        "click",
        () => { window.__clicked = true; },
      );
    </script>
  </body>
</html>
"""


def _write_fixture(tmp_path: Path) -> str:
    page = tmp_path / "fixture.html"
    page.write_text(_FIXTURE_HTML, encoding="utf-8")
    return page.as_uri()


def _recording_with(actions: list[RecordedAction], starting_url: str = "about:blank") -> Recording:
    return Recording(
        name="executor-fixture",
        created_at=datetime.now(UTC),
        starting_url=starting_url,
        actions=actions,
    )


def _click_action(selector: ElementSelector, *, sequence: int = 1) -> RecordedAction:
    return RecordedAction(
        sequence=sequence,
        timestamp=datetime.now(UTC),
        action_type=ActionType.CLICK,
        payload=ClickPayload(button="left"),
        selector=selector,
        url="about:blank",
    )


def _input_action(
    selector: ElementSelector,
    value: str,
    *,
    sequence: int = 1,
    is_parameterized: bool = False,
    parameter_name: str | None = None,
) -> RecordedAction:
    return RecordedAction(
        sequence=sequence,
        timestamp=datetime.now(UTC),
        action_type=ActionType.INPUT,
        payload=InputPayload(value=value, clear_first=True),
        selector=selector,
        url="about:blank",
        is_parameterized=is_parameterized,
        parameter_name=parameter_name,
    )


@pytest.mark.integration
async def test_executor_replays_click_recording(tmp_path: Path) -> None:
    fixture_url = _write_fixture(tmp_path)
    recording = _recording_with(
        [_click_action(ElementSelector(test_id="save-btn"))],
        starting_url=fixture_url,
    )
    async with BrowserSession(headless=True) as session:
        await session.page.goto(fixture_url)
        executor = Executor(
            session.page,
            recording,
            screenshots_dir=tmp_path / "screenshots",
            dom_dir=tmp_path / "dom",
        )
        result = await executor.run()
        clicked = await session.page.evaluate("() => window.__clicked === true")

    assert result.status == ExecutionStatus.SUCCESS
    assert len(result.executions) == 1
    assert result.executions[0].status == ExecutionStatus.SUCCESS
    assert len(result.executions[0].attempts) == 1
    assert result.executions[0].attempts[0].selector_used is not None
    assert result.executions[0].attempts[0].selector_used.test_id == "save-btn"
    assert clicked is True


@pytest.mark.integration
async def test_executor_falls_back_through_selector_strategies(tmp_path: Path) -> None:
    fixture_url = _write_fixture(tmp_path)
    # Bogus test_id and css; valid role+name.
    recording = _recording_with(
        [
            _click_action(
                ElementSelector(
                    test_id="not-a-real-testid",
                    role="button",
                    accessible_name="Save",
                    css="#nonexistent",
                )
            )
        ],
        starting_url=fixture_url,
    )
    async with BrowserSession(headless=True) as session:
        await session.page.goto(fixture_url)
        executor = Executor(
            session.page,
            recording,
            screenshots_dir=tmp_path / "screenshots",
            dom_dir=tmp_path / "dom",
        )
        result = await executor.run()

    assert result.status == ExecutionStatus.SUCCESS
    used = result.executions[0].attempts[0].selector_used
    assert used is not None
    assert used.role == "button"
    assert used.accessible_name == "Save"
    assert used.test_id is None
    assert used.css is None


@pytest.mark.integration
async def test_executor_captures_artifacts_on_failure(tmp_path: Path) -> None:
    fixture_url = _write_fixture(tmp_path)
    recording = _recording_with(
        [_click_action(ElementSelector(test_id="does-not-exist"))],
        starting_url=fixture_url,
    )
    async with BrowserSession(headless=True) as session:
        await session.page.goto(fixture_url)
        executor = Executor(
            session.page,
            recording,
            screenshots_dir=tmp_path / "screenshots",
            dom_dir=tmp_path / "dom",
        )
        result = await executor.run()

    assert result.status == ExecutionStatus.FAILED
    attempt = result.executions[0].attempts[0]
    assert attempt.status == ExecutionStatus.FAILED
    assert attempt.failure_mode == FailureMode.ELEMENT_NOT_FOUND
    assert attempt.screenshot_path is not None
    assert Path(attempt.screenshot_path).exists()
    assert attempt.dom_snapshot_path is not None
    assert Path(attempt.dom_snapshot_path).exists()
    # Accessibility snapshot may be None on some Chromium builds; treat as best-effort.
    if attempt.accessibility_snapshot_path is not None:
        assert Path(attempt.accessibility_snapshot_path).exists()


@pytest.mark.integration
async def test_executor_substitutes_parameters(tmp_path: Path) -> None:
    fixture_url = _write_fixture(tmp_path)
    recording = _recording_with(
        [
            _input_action(
                ElementSelector(test_id="email-field"),
                value="placeholder@example.com",
                is_parameterized=True,
                parameter_name="email",
            )
        ],
        starting_url=fixture_url,
    )
    async with BrowserSession(headless=True) as session:
        await session.page.goto(fixture_url)
        executor = Executor(
            session.page,
            recording,
            screenshots_dir=tmp_path / "screenshots",
            dom_dir=tmp_path / "dom",
            parameter_values={"email": "alice@example.com"},
        )
        result = await executor.run()
        actual = await session.page.input_value("#email")

    assert result.status == ExecutionStatus.SUCCESS
    assert actual == "alice@example.com"


@pytest.mark.integration
async def test_executor_rejects_ambiguous_selector(tmp_path: Path) -> None:
    fixture_url = _write_fixture(tmp_path)
    # CSS class .dup matches two spans.
    recording = _recording_with(
        [_click_action(ElementSelector(css=".dup"))],
        starting_url=fixture_url,
    )
    async with BrowserSession(headless=True) as session:
        await session.page.goto(fixture_url)
        executor = Executor(
            session.page,
            recording,
            screenshots_dir=tmp_path / "screenshots",
            dom_dir=tmp_path / "dom",
        )
        result = await executor.run()

    assert result.status == ExecutionStatus.FAILED
    attempt = result.executions[0].attempts[0]
    assert attempt.failure_mode == FailureMode.ELEMENT_NOT_FOUND


def test_selector_resolution_error_is_exception() -> None:
    err = SelectorResolutionError("boom")
    assert isinstance(err, Exception)
    assert str(err) == "boom"
