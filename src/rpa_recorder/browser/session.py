"""`BrowserSession` async context manager wrapping Playwright Chromium."""

from contextlib import AsyncExitStack
from typing import TYPE_CHECKING, Any, Self

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)

if TYPE_CHECKING:
    from types import TracebackType


class BrowserSession:
    """Async context manager for a single Chromium browser session.

    Wraps Playwright start, browser launch, BrowserContext creation, and one
    Page. When `trace_path` is set, starts a trace with screenshots/snapshots/
    sources and writes the zip on exit. When `har_path` is set, the
    BrowserContext records a HAR file (written automatically on context close).
    """

    def __init__(
        self,
        *,
        headless: bool = False,
        storage_state: str | None = None,
        viewport: dict[str, int] | None = None,
        locale: str = "en-US",
        timezone_id: str = "UTC",
        trace_path: str | None = None,
        har_path: str | None = None,
    ) -> None:
        self._headless = headless
        self._storage_state = storage_state
        self._viewport = viewport
        self._locale = locale
        self._timezone_id = timezone_id
        self._trace_path = trace_path
        self._har_path = har_path
        self._stack: AsyncExitStack | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    async def __aenter__(self) -> Self:
        stack = AsyncExitStack()
        await stack.__aenter__()
        try:
            pw: Playwright = await stack.enter_async_context(async_playwright())
            browser: Browser = await pw.chromium.launch(headless=self._headless)
            stack.push_async_callback(browser.close)

            context_kwargs: dict[str, Any] = {
                "locale": self._locale,
                "timezone_id": self._timezone_id,
            }
            if self._viewport is not None:
                context_kwargs["viewport"] = self._viewport
            if self._storage_state is not None:
                context_kwargs["storage_state"] = self._storage_state
            if self._har_path is not None:
                context_kwargs["record_har_path"] = self._har_path

            context = await browser.new_context(**context_kwargs)
            stack.push_async_callback(context.close)

            if self._trace_path is not None:
                await context.tracing.start(
                    screenshots=True,
                    snapshots=True,
                    sources=True,
                )
                trace_path = self._trace_path

                async def _stop_tracing() -> None:
                    await context.tracing.stop(path=trace_path)

                stack.push_async_callback(_stop_tracing)

            page = await context.new_page()
        except BaseException:
            await stack.aclose()
            raise

        self._stack = stack
        self._context = context
        self._page = page
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if self._stack is not None:
            await self._stack.__aexit__(exc_type, exc_val, exc_tb)
        self._stack = None
        self._context = None
        self._page = None

    @property
    def page(self) -> Page:
        if self._page is None:
            raise RuntimeError("BrowserSession is not entered")
        return self._page

    @property
    def context(self) -> BrowserContext:
        if self._context is None:
            raise RuntimeError("BrowserSession is not entered")
        return self._context
