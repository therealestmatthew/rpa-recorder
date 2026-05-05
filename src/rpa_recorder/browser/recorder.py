"""Recorder that injects the page-side script and emits `RecordedAction` rows.

The Recorder attaches to a Playwright `Page`, exposes `__rpa_capture` to the
page, and injects `assets/recorder_inject.js` as an init script so it runs in
every frame on every navigation. The page-side script forwards click / input /
change / keydown envelopes; this module normalizes them into `RecordedAction`
rows. Page-level `request`, `response`, and `framenavigated` events feed the
network log and produce `NAVIGATE` actions for SPA-style navigations.
"""

from contextlib import suppress
from datetime import UTC, datetime
from importlib.resources import files
from typing import TYPE_CHECKING, Any

# Runtime imports: Playwright introspects listener-handler signatures via
# `inspect.signature()`, which forces annotation evaluation. Frame / Page /
# Request / Response must therefore resolve at runtime, not under
# TYPE_CHECKING.
from playwright.async_api import Frame, Page, Request, Response  # noqa: TC002
from pydantic import ValidationError

from rpa_recorder.models import (
    ActionType,
    ClickPayload,
    ElementContext,
    ElementSelector,
    InputPayload,
    NavigatePayload,
    NetworkEvent,
    RecordedAction,
    Recording,
    SelectPayload,
)

if TYPE_CHECKING:
    from rpa_recorder.models.actions import ActionPayload


def _load_inject_script() -> str:
    """Read the page-side recorder script from the bundled assets package."""
    return files("rpa_recorder.assets").joinpath("recorder_inject.js").read_text(encoding="utf-8")


class Recorder:
    """Attach to a `Page`, capture user interactions, produce a `Recording`.

    Lifecycle:
        - `await recorder.start()` exposes `__rpa_capture` to the page,
          installs the init script for future navigations, evaluates it on
          the current document, and binds page-level network/navigation
          listeners.
        - The page emits envelopes through `__rpa_capture`; this class
          normalizes each into a `RecordedAction` with an incrementing
          `sequence` and the page's current `url`.
        - `await recorder.stop()` detaches Python-side listeners and makes
          subsequent envelopes no-ops.
        - `recorder.get_recording()` returns the assembled `Recording`.

    Concurrency: handlers do not `await` between mutating `_sequence` and
    appending to `_actions`, so under asyncio's single-threaded model
    captures stay ordered without an explicit lock.
    """

    def __init__(
        self,
        page: Page,
        *,
        name: str = "recording",
        starting_url: str | None = None,
    ) -> None:
        self._page = page
        self._name = name
        self._starting_url = starting_url
        self._actions: list[RecordedAction] = []
        self._network_log: list[NetworkEvent] = []
        self._sequence = 0
        self._started_at: datetime | None = None
        self._started = False
        self._stopped = False
        self._last_main_frame_url: str | None = None

    async def start(self) -> None:
        """Expose the capture binding, inject the script, bind page listeners."""
        if self._started:
            raise RuntimeError("Recorder is already started")
        await self._page.expose_function("__rpa_capture", self._on_capture)
        script = _load_inject_script()
        await self._page.add_init_script(script=script)
        # add_init_script only runs on future navigations; evaluate once for
        # whatever document is currently loaded so we don't miss the first page.
        with suppress(Exception):
            await self._page.evaluate(script)
        self._page.on("request", self._on_request)
        self._page.on("response", self._on_response)
        self._page.on("framenavigated", self._on_framenavigated)
        self._started_at = datetime.now(UTC)
        self._started = True

    async def stop(self) -> None:
        """Detach page listeners and freeze the recording."""
        if self._stopped:
            return
        self._stopped = True
        with suppress(KeyError, ValueError):
            self._page.remove_listener("request", self._on_request)
        with suppress(KeyError, ValueError):
            self._page.remove_listener("response", self._on_response)
        with suppress(KeyError, ValueError):
            self._page.remove_listener("framenavigated", self._on_framenavigated)

    def get_recording(self) -> Recording:
        """Return the captured `Recording`. Requires `start()` to have run."""
        if self._started_at is None:
            raise RuntimeError("Recorder was not started")
        if self._starting_url is not None:
            starting = self._starting_url
        elif self._actions:
            starting = self._actions[0].url
        else:
            starting = self._page.url
        return Recording(
            name=self._name,
            created_at=self._started_at,
            starting_url=starting,
            actions=list(self._actions),
            network_log=list(self._network_log),
        )

    @property
    def actions(self) -> list[RecordedAction]:
        """Snapshot of `RecordedAction` rows captured so far."""
        return list(self._actions)

    @property
    def network_log(self) -> list[NetworkEvent]:
        """Snapshot of `NetworkEvent` rows captured so far."""
        return list(self._network_log)

    # ----- capture pipeline -------------------------------------------------

    async def _on_capture(self, raw: dict[str, Any]) -> None:
        if self._stopped:
            return
        try:
            action = self._build_action(raw)
        except ValidationError, ValueError, TypeError:
            return
        if action is not None:
            self._actions.append(action)

    def _build_action(self, raw: dict[str, Any]) -> RecordedAction | None:
        event_type = raw.get("event_type")
        target = raw.get("target") or {}
        payload_dict = raw.get("payload") or {}

        payload: ActionPayload
        if event_type == "click":
            action_type = ActionType.CLICK
            payload = ClickPayload(**payload_dict)
        elif event_type == "input":
            action_type = ActionType.INPUT
            payload = InputPayload(**payload_dict)
        elif event_type == "change":
            tag = str(target.get("tag") or "").lower()
            if tag == "select":
                action_type = ActionType.SELECT
                payload = SelectPayload(**payload_dict)
            else:
                action_type = ActionType.INPUT
                payload = InputPayload(**payload_dict)
        elif event_type == "keydown":
            action_type = ActionType.KEY_PRESS
            payload = dict(payload_dict)
        else:
            return None

        selector = ElementSelector(
            role=target.get("role"),
            accessible_name=target.get("accessible_name"),
            test_id=target.get("test_id"),
            text_content=target.get("visible_text"),
            css=target.get("css"),
            xpath=target.get("xpath"),
        )
        element_context = ElementContext(
            tag=str(target.get("tag") or ""),
            attributes=dict(target.get("attributes") or {}),
            visible_text=target.get("visible_text"),
            bounding_box=target.get("bounding_box"),
            is_visible=bool(target.get("is_visible", True)),
            is_enabled=bool(target.get("is_enabled", True)),
            parent_form_id=target.get("parent_form_id"),
            nearby_labels=list(target.get("nearby_labels") or []),
        )

        viewport_raw = raw.get("viewport")
        viewport = viewport_raw if isinstance(viewport_raw, dict) else None

        self._sequence += 1
        return RecordedAction(
            sequence=self._sequence,
            timestamp=self._parse_ts(raw.get("timestamp_ms")),
            action_type=action_type,
            payload=payload,
            selector=selector,
            element_context=element_context,
            url=self._page.url,
            page_title=raw.get("page_title"),
            frame_url=raw.get("frame_url"),
            viewport=viewport,
        )

    @staticmethod
    def _parse_ts(value: object) -> datetime:
        if isinstance(value, int | float) and not isinstance(value, bool):
            return datetime.fromtimestamp(float(value) / 1000.0, tz=UTC)
        return datetime.now(UTC)

    # ----- page-level listeners --------------------------------------------

    def _on_request(self, request: Request) -> None:
        if self._stopped:
            return
        self._network_log.append(
            NetworkEvent(
                timestamp=datetime.now(UTC),
                method=request.method,
                url=request.url,
                request_headers=dict(request.headers),
            )
        )

    def _on_response(self, response: Response) -> None:
        if self._stopped:
            return
        for evt in reversed(self._network_log):
            if evt.url == response.url and evt.status is None:
                evt.status = response.status
                evt.response_summary = f"{response.status} {response.status_text}"
                return

    def _on_framenavigated(self, frame: Frame) -> None:
        if self._stopped:
            return
        if frame is not self._page.main_frame:
            return
        new_url = frame.url
        if not new_url or new_url == self._last_main_frame_url:
            return
        self._last_main_frame_url = new_url
        self._sequence += 1
        self._actions.append(
            RecordedAction(
                sequence=self._sequence,
                timestamp=datetime.now(UTC),
                action_type=ActionType.NAVIGATE,
                payload=NavigatePayload(url=new_url),
                url=new_url,
                page_title=None,
                frame_url=new_url,
            )
        )
