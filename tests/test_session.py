"""Integration tests for `BrowserSession` against headless Chromium."""

from typing import TYPE_CHECKING

import pytest

from rpa_recorder.browser.session import BrowserSession

if TYPE_CHECKING:
    from pathlib import Path


async def test_page_property_raises_outside_context() -> None:
    session = BrowserSession()
    with pytest.raises(RuntimeError):
        _ = session.page


async def test_context_property_raises_outside_context() -> None:
    session = BrowserSession()
    with pytest.raises(RuntimeError):
        _ = session.context


@pytest.mark.integration
async def test_session_opens_and_closes_cleanly() -> None:
    async with BrowserSession(headless=True) as session:
        await session.page.goto("about:blank")
        assert session.page.url == "about:blank"


@pytest.mark.integration
async def test_session_uses_custom_viewport() -> None:
    async with BrowserSession(
        headless=True,
        viewport={"width": 800, "height": 600},
    ) as session:
        await session.page.goto("about:blank")
        size = session.page.viewport_size
        assert size is not None
        assert size["width"] == 800
        assert size["height"] == 600


@pytest.mark.integration
async def test_session_writes_trace_zip(tmp_path: Path) -> None:
    trace_file = tmp_path / "trace.zip"
    async with BrowserSession(headless=True, trace_path=str(trace_file)) as session:
        await session.page.goto("about:blank")
    assert trace_file.exists()
    assert trace_file.stat().st_size > 0


@pytest.mark.integration
async def test_session_writes_har_file(tmp_path: Path) -> None:
    har_file = tmp_path / "network.har"
    async with BrowserSession(headless=True, har_path=str(har_file)) as session:
        await session.page.goto("about:blank")
    assert har_file.exists()
    assert har_file.stat().st_size > 0


@pytest.mark.integration
async def test_session_resets_after_exit() -> None:
    session = BrowserSession(headless=True)
    async with session:
        await session.page.goto("about:blank")
    with pytest.raises(RuntimeError):
        _ = session.page
    with pytest.raises(RuntimeError):
        _ = session.context
