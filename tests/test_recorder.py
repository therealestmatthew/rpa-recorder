"""Integration tests for `Recorder` against a static HTML fixture."""

from typing import TYPE_CHECKING

import pytest

from rpa_recorder.browser.recorder import Recorder
from rpa_recorder.browser.session import BrowserSession
from rpa_recorder.models import (
    ActionType,
    ClickPayload,
    InputPayload,
    NavigatePayload,
    RecordedAction,
)

if TYPE_CHECKING:
    from pathlib import Path

    from playwright.async_api import Page


_FIXTURE_HTML = """<!doctype html>
<html lang="en">
  <head><title>Login</title></head>
  <body>
    <form id="login-form">
      <label for="email">Email</label>
      <input id="email" name="email" type="email" placeholder="you@example.com" />

      <label for="password">Password</label>
      <input id="password" name="password" type="password" />

      <button id="save" data-testid="save-btn" aria-label="Save" type="button">
        Save
      </button>
    </form>
  </body>
</html>
"""


def _write_fixture(tmp_path: Path) -> str:
    page = tmp_path / "fixture.html"
    page.write_text(_FIXTURE_HTML, encoding="utf-8")
    return page.as_uri()


async def _wait_capture(session_page: Page, count: int) -> None:
    # Allow a generous timeout — first run on slow CI can be sluggish.
    await session_page.wait_for_function(
        f"() => (window.__rpaCaptureCount || 0) >= {count}",
        timeout=5000,
    )


@pytest.mark.integration
async def test_recorder_captures_click(tmp_path: Path) -> None:
    fixture_url = _write_fixture(tmp_path)
    async with BrowserSession(headless=True) as session:
        recorder = Recorder(session.page, name="click-test")
        await recorder.start()
        await session.page.goto(fixture_url)
        await session.page.click("#save")
        await _wait_capture(session.page, 1)
        await recorder.stop()
        rec = recorder.get_recording()

    assert rec.name == "click-test"
    assert rec.starting_url.startswith("file://")

    clicks = [a for a in rec.actions if a.action_type == ActionType.CLICK]
    assert len(clicks) == 1
    click = clicks[0]
    assert isinstance(click.payload, ClickPayload)
    assert click.payload.button == "left"

    assert click.selector is not None
    assert click.selector.test_id == "save-btn"
    assert click.selector.role == "button"
    assert click.selector.accessible_name == "Save"
    assert click.selector.css is not None
    assert click.selector.xpath is not None

    ctx = click.element_context
    assert ctx is not None
    assert ctx.tag == "button"
    assert ctx.parent_form_id == "login-form"
    assert ctx.is_enabled is True
    assert ctx.is_visible is True
    assert ctx.attributes.get("data-testid") == "save-btn"

    assert click.url.startswith("file://")
    assert click.frame_url is not None
    assert click.viewport is not None
    assert click.viewport["width"] > 0


@pytest.mark.integration
async def test_recorder_redacts_sensitive_input(tmp_path: Path) -> None:
    fixture_url = _write_fixture(tmp_path)
    async with BrowserSession(headless=True) as session:
        recorder = Recorder(session.page, name="input-test")
        await recorder.start()
        await session.page.goto(fixture_url)
        await session.page.fill("#email", "alice@example.com")
        await session.page.fill("#password", "hunter2")
        await _wait_capture(session.page, 2)
        await recorder.stop()
        rec = recorder.get_recording()

    inputs = [a for a in rec.actions if a.action_type == ActionType.INPUT]
    assert len(inputs) >= 2

    def _attr_type(a: RecordedAction) -> str:
        return (a.element_context.attributes.get("type") if a.element_context else "") or ""

    email = next(a for a in inputs if _attr_type(a) == "email")
    pw = next(a for a in inputs if _attr_type(a) == "password")

    assert isinstance(email.payload, InputPayload)
    assert email.payload.value == "alice@example.com"
    assert email.payload.is_sensitive is False

    assert isinstance(pw.payload, InputPayload)
    assert pw.payload.value == "hunter2"
    assert pw.payload.is_sensitive is True

    # Raw dump preserves the value; redacted dump replaces it.
    raw = pw.model_dump()
    redacted = pw.model_dump(context={"redact_secrets": True})
    assert raw["payload"]["value"] == "hunter2"
    assert redacted["payload"]["value"] == "***REDACTED***"


@pytest.mark.integration
async def test_recorder_emits_navigate_on_main_frame(tmp_path: Path) -> None:
    fixture_url = _write_fixture(tmp_path)
    async with BrowserSession(headless=True) as session:
        recorder = Recorder(session.page, name="navigate-test")
        await recorder.start()
        await session.page.goto(fixture_url)
        await session.page.wait_for_load_state("load")
        await recorder.stop()
        rec = recorder.get_recording()

    navs = [a for a in rec.actions if a.action_type == ActionType.NAVIGATE]
    assert len(navs) >= 1
    nav = navs[-1]
    assert isinstance(nav.payload, NavigatePayload)
    assert nav.payload.url.startswith("file://")
    assert nav.url == nav.payload.url


async def test_get_recording_before_start_raises() -> None:
    async with BrowserSession(headless=True) as session:
        recorder = Recorder(session.page)
        with pytest.raises(RuntimeError):
            recorder.get_recording()


async def test_double_start_raises() -> None:
    async with BrowserSession(headless=True) as session:
        recorder = Recorder(session.page)
        await recorder.start()
        with pytest.raises(RuntimeError):
            await recorder.start()
        await recorder.stop()
