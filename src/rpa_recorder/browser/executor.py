"""Executor: replay a `Recording` against a `Page` with multi-strategy selectors.

Each `RecordedAction` is dispatched against a Playwright locator resolved by
the spec's strategy order: `test_id` → `role + accessible_name` →
`text_content` → `css` → `xpath`. Each candidate must match exactly one
element to win; otherwise the executor falls through. On failure we capture
a screenshot, the rendered DOM, and Playwright's accessibility tree to disk
under `screenshots_dir/<run_id>/` and `dom_dir/<run_id>/`, then dispatch to
`_attempt_recovery` (stubbed in M6, populated by the recovery engine in M10).
"""

import json
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

# Runtime imports: Error and TimeoutError are runtime-used in `except` clauses.
# ConsoleMessage is annotation-only on `_on_console` but Playwright introspects
# listener-handler signatures via `inspect.signature()`, so it also needs
# runtime resolution.
from playwright.async_api import ConsoleMessage
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from rpa_recorder.models import (
    ActionExecution,
    ActionType,
    ClickPayload,
    ElementSelector,
    ExecutionAttempt,
    ExecutionStatus,
    FailureMode,
    InputPayload,
    NavigatePayload,
    RecordedAction,
    Recording,
    RecoveryAction,
    RunResult,
    SelectPayload,
)

if TYPE_CHECKING:
    from playwright.async_api import Locator, Page


class SelectorResolutionError(Exception):
    """Raised when no `ElementSelector` strategy resolves to exactly one element."""


def _classify_failure(error: BaseException) -> FailureMode:
    if isinstance(error, SelectorResolutionError):
        return FailureMode.ELEMENT_NOT_FOUND
    if isinstance(error, PlaywrightTimeoutError):
        return FailureMode.TIMEOUT
    message = str(error).lower()
    if any(s in message for s in ("not visible", "not interactable", "is hidden")):
        return FailureMode.ELEMENT_NOT_INTERACTABLE
    if "navigation" in message:
        return FailureMode.NAVIGATION_FAILED
    return FailureMode.UNKNOWN


class Executor:
    """Replay a `Recording` against a `Page` with multi-strategy selectors."""

    def __init__(
        self,
        page: Page,
        recording: Recording,
        *,
        screenshots_dir: Path,
        dom_dir: Path,
        parameter_values: dict[str, str] | None = None,
        run_id: UUID | None = None,
    ) -> None:
        self._page = page
        self._recording = recording
        self._screenshots_dir = Path(screenshots_dir)
        self._dom_dir = Path(dom_dir)
        self._parameter_values = dict(parameter_values or {})
        self._run_id = run_id or uuid4()
        self._console_log: list[str] = []
        self._js_errors: list[str] = []
        self._page.on("console", self._on_console)
        self._page.on("pageerror", self._on_pageerror)

    @property
    def run_id(self) -> UUID:
        """The UUID assigned to the run produced by this executor."""
        return self._run_id

    async def run(self) -> RunResult:
        """Replay every action in order; aggregate outcomes into a `RunResult`."""
        started = datetime.now(UTC)
        executions: list[ActionExecution] = []
        overall_status = ExecutionStatus.SUCCESS

        for action in self._recording.actions:
            execution = await self._execute_one(action)
            executions.append(execution)
            if execution.status == ExecutionStatus.FAILED:
                overall_status = ExecutionStatus.FAILED

        return RunResult(
            id=self._run_id,
            recording_id=self._recording.id,
            started_at=started,
            ended_at=datetime.now(UTC),
            status=overall_status,
            parameter_values=dict(self._parameter_values),
            executions=executions,
        )

    # ----- per-action execution ---------------------------------------------

    async def _execute_one(self, action: RecordedAction) -> ActionExecution:
        attempt_started = datetime.now(UTC)
        console_mark = len(self._console_log)
        errors_mark = len(self._js_errors)
        selector_used: ElementSelector | None = action.selector

        try:
            if action.action_type == ActionType.NAVIGATE:
                await self._dispatch_navigate(action)
            else:
                if action.selector is None:
                    raise SelectorResolutionError(f"action #{action.sequence} has no selector")
                locator, selector_used = await self._resolve_selector(action.selector)
                await self._dispatch_locator_action(action, locator)
        except (SelectorResolutionError, PlaywrightError, ValueError) as exc:
            return await self._record_failure(
                action,
                exc,
                attempt_started=attempt_started,
                selector_used=selector_used,
                console_mark=console_mark,
                errors_mark=errors_mark,
            )

        ended = datetime.now(UTC)
        attempt = ExecutionAttempt(
            attempt_number=1,
            started_at=attempt_started,
            ended_at=ended,
            status=ExecutionStatus.SUCCESS,
            selector_used=selector_used,
            console_log=list(self._console_log[console_mark:]),
            js_errors=list(self._js_errors[errors_mark:]),
        )
        return ActionExecution(
            action_id=action.id,
            status=ExecutionStatus.SUCCESS,
            attempts=[attempt],
            duration_ms=int((ended - attempt_started).total_seconds() * 1000),
        )

    async def _record_failure(
        self,
        action: RecordedAction,
        error: BaseException,
        *,
        attempt_started: datetime,
        selector_used: ElementSelector | None,
        console_mark: int,
        errors_mark: int,
    ) -> ActionExecution:
        ended = datetime.now(UTC)
        paths = await self._capture_failure(action, attempt_number=1)
        attempt = ExecutionAttempt(
            attempt_number=1,
            started_at=attempt_started,
            ended_at=ended,
            status=ExecutionStatus.FAILED,
            failure_mode=_classify_failure(error),
            error_message=str(error),
            selector_used=selector_used,
            screenshot_path=paths["screenshot"],
            dom_snapshot_path=paths["dom"],
            accessibility_snapshot_path=paths["a11y"],
            console_log=list(self._console_log[console_mark:]),
            js_errors=list(self._js_errors[errors_mark:]),
        )
        recovery = await self._attempt_recovery(action, attempt)
        recovered = recovery is not None and recovery.succeeded
        return ActionExecution(
            action_id=action.id,
            status=ExecutionStatus.RECOVERED if recovered else ExecutionStatus.FAILED,
            attempts=[attempt],
            recovery=recovery,
            duration_ms=int((ended - attempt_started).total_seconds() * 1000),
        )

    # ----- selector resolution ---------------------------------------------

    async def _resolve_selector(self, sel: ElementSelector) -> tuple[Locator, ElementSelector]:
        """Try strategies in order; return the locator + the selector that won."""
        candidates: list[tuple[Locator, ElementSelector]] = []
        if sel.test_id:
            candidates.append(
                (
                    self._page.get_by_test_id(sel.test_id),
                    ElementSelector(test_id=sel.test_id),
                )
            )
        if sel.role and sel.accessible_name:
            candidates.append(
                (
                    self._page.get_by_role(sel.role, name=sel.accessible_name),  # type: ignore[arg-type]
                    ElementSelector(role=sel.role, accessible_name=sel.accessible_name),
                )
            )
        if sel.text_content:
            candidates.append(
                (
                    self._page.get_by_text(sel.text_content, exact=True),
                    ElementSelector(text_content=sel.text_content),
                )
            )
        if sel.css:
            candidates.append(
                (
                    self._page.locator(sel.css),
                    ElementSelector(css=sel.css),
                )
            )
        if sel.xpath:
            candidates.append(
                (
                    self._page.locator(f"xpath={sel.xpath}"),
                    ElementSelector(xpath=sel.xpath),
                )
            )

        for locator, used in candidates:
            try:
                count = await locator.count()
            except PlaywrightError:
                continue
            if count == 1:
                return locator, used

        raise SelectorResolutionError(
            f"no selector strategy resolved uniquely for {sel.model_dump()}"
        )

    # ----- typed dispatch ---------------------------------------------------

    async def _dispatch_locator_action(self, action: RecordedAction, locator: Locator) -> None:
        payload = action.payload
        if action.action_type == ActionType.CLICK:
            if isinstance(payload, ClickPayload):
                await locator.click(
                    button=payload.button,
                    modifiers=payload.modifiers,  # type: ignore[arg-type]
                )
            else:
                await locator.click()
        elif action.action_type == ActionType.INPUT:
            value = self._resolve_input_value(action)
            clear_first = payload.clear_first if isinstance(payload, InputPayload) else True
            if clear_first:
                await locator.fill("")
            await locator.fill(value)
        elif action.action_type == ActionType.SELECT:
            if not isinstance(payload, SelectPayload):
                raise ValueError("SELECT action missing SelectPayload")
            await locator.select_option(value=payload.values)
        elif action.action_type == ActionType.KEY_PRESS:
            key = payload.get("key", "Enter") if isinstance(payload, dict) else "Enter"
            await locator.press(str(key))
        elif action.action_type == ActionType.HOVER:
            await locator.hover()
        else:
            raise ValueError(f"action_type {action.action_type.value!r} not supported by executor")

    async def _dispatch_navigate(self, action: RecordedAction) -> None:
        payload = action.payload
        if isinstance(payload, NavigatePayload):
            await self._page.goto(payload.url, wait_until=payload.wait_until)
            return
        if isinstance(payload, dict):
            url = payload.get("url")
            if not url:
                raise ValueError("NAVIGATE action missing url")
            await self._page.goto(str(url))
            return
        raise ValueError("NAVIGATE action requires NavigatePayload or dict-with-url")

    def _resolve_input_value(self, action: RecordedAction) -> str:
        if action.is_parameterized and action.parameter_name:
            value = self._parameter_values.get(action.parameter_name)
            if value is not None:
                return value
        payload = action.payload
        if isinstance(payload, InputPayload):
            return payload.value
        if isinstance(payload, dict):
            value = payload.get("value")
            if value is not None:
                return str(value)
        return ""

    # ----- failure capture --------------------------------------------------

    async def _capture_failure(
        self, action: RecordedAction, *, attempt_number: int
    ) -> dict[str, str | None]:
        run_dir_screens = self._screenshots_dir / str(self._run_id)
        run_dir_dom = self._dom_dir / str(self._run_id)
        run_dir_screens.mkdir(parents=True, exist_ok=True)
        run_dir_dom.mkdir(parents=True, exist_ok=True)

        ss_path = run_dir_screens / f"{action.sequence}_{attempt_number}.png"
        dom_path = run_dir_dom / f"{action.sequence}_{attempt_number}.html"
        a11y_path = run_dir_dom / f"{action.sequence}_{attempt_number}.a11y.json"

        with suppress(PlaywrightError, OSError):
            await self._page.screenshot(path=str(ss_path))
        with suppress(PlaywrightError, OSError):
            html = await self._page.content()
            dom_path.write_text(html, encoding="utf-8")
        with suppress(PlaywrightError, OSError, AttributeError):
            tree = await self._page.accessibility.snapshot()  # type: ignore[attr-defined]
            a11y_path.write_text(
                json.dumps(tree, default=str, indent=2),
                encoding="utf-8",
            )

        return {
            "screenshot": str(ss_path) if ss_path.exists() else None,
            "dom": str(dom_path) if dom_path.exists() else None,
            "a11y": str(a11y_path) if a11y_path.exists() else None,
        }

    # ----- recovery hook (filled in M10) -----------------------------------

    async def _attempt_recovery(
        self,
        action: RecordedAction,  # noqa: ARG002
        attempt: ExecutionAttempt,  # noqa: ARG002
    ) -> RecoveryAction | None:
        """Stub: M10 will plug the `RecoveryEngine` in here."""
        return None

    # ----- page-level listeners --------------------------------------------

    def _on_console(self, msg: ConsoleMessage) -> None:
        with suppress(Exception):
            self._console_log.append(f"[{msg.type}] {msg.text}")

    def _on_pageerror(self, error: Any) -> None:
        with suppress(Exception):
            self._js_errors.append(str(error))
