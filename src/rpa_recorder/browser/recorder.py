"""Recorder that injects the page-side script and emits `RecordedAction` rows.

The Recorder attaches to a Playwright `Page`, exposes `__rpa_capture` to the
page, and bundles `page_scripts/{shared/text_utils, shared/selectors,
recorder/inject}` as an init script so it runs in every frame on every
navigation. The page-side scripts forward click / input / change / keydown
envelopes; this module normalizes them into `RecordedAction` rows.
Page-level `request`, `response`, and `framenavigated` events feed the
network log and produce `NAVIGATE` actions for SPA-style navigations.

When a `BronzeWriter` is provided, raw envelopes are also pushed onto a
bounded `asyncio.Queue` and a background drain task batches them into the
bronze JSONL. The capture handler never awaits the bronze write — it does
a non-blocking `put_nowait`, dropping (with a structlog warning) on
`QueueFull` so a stalled disk cannot back up the event loop.
"""

import asyncio
from contextlib import suppress
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import structlog

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
from rpa_recorder.page_scripts import bundle

if TYPE_CHECKING:
    from rpa_recorder.medallion import BronzeWriter
    from rpa_recorder.models.actions import ActionPayload

_log = structlog.get_logger(__name__)

_BRONZE_BATCH_SIZE: int = 10
_BRONZE_BATCH_WAIT_SECS: float = 0.1
_BRONZE_DRAIN_TIMEOUT_SECS: float = 5.0


def _build_inject_bundle() -> str:
    """Bundle the recorder-side init script (shared utilities first, then inject)."""
    return bundle("shared/text_utils", "shared/selectors", "recorder/inject")


class Recorder:
    """Attach to a `Page`, capture user interactions, produce a `Recording`.

    Lifecycle:
        - `await recorder.start()` exposes `__rpa_capture` to the page,
          installs the init bundle for future navigations, evaluates it on
          the current document, and binds page-level network/navigation
          listeners. If `bronze` was provided, also creates the bounded
          envelope queue and starts the drain task.
        - The page emits envelopes through `__rpa_capture`; this class
          normalizes each into a `RecordedAction` with an incrementing
          `sequence` and the page's current `url`. Raw envelopes also land
          in the bronze queue (non-blocking).
        - `await recorder.stop()` detaches Python-side listeners, flushes
          the bronze queue with a 5 s timeout, and makes subsequent
          envelopes no-ops.
        - `recorder.get_recording()` returns the assembled `Recording`.

    Concurrency: the capture handler does not `await` between mutating
    `_sequence` and appending to `_actions`, so under asyncio's
    single-threaded model captures stay ordered without an explicit lock.
    The bronze enqueue (`put_nowait`) is non-awaiting and preserves that
    invariant.
    """

    def __init__(
        self,
        page: Page,
        *,
        name: str = "recording",
        starting_url: str | None = None,
        bronze: BronzeWriter | None = None,
        recording_id: UUID | None = None,
        bronze_queue_size: int = 1000,
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

        # Bronze plumbing — all None when bronze writes are disabled.
        self._bronze = bronze
        self._recording_id = recording_id or uuid4()
        self._bronze_queue_size = bronze_queue_size
        self._bronze_queue: asyncio.Queue[dict[str, Any] | None] | None = None
        self._bronze_drain_task: asyncio.Task[None] | None = None

    @property
    def recording_id(self) -> UUID:
        """The UUID assigned to the recording produced by this recorder."""
        return self._recording_id

    async def start(self) -> None:
        """Expose the capture binding, inject the script, bind page listeners."""
        if self._started:
            raise RuntimeError("Recorder is already started")
        await self._page.expose_function("__rpa_capture", self._on_capture)
        script = _build_inject_bundle()
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

        if self._bronze is not None:
            self._bronze_queue = asyncio.Queue(maxsize=self._bronze_queue_size)
            self._bronze_drain_task = asyncio.create_task(self._drain_bronze())

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

        if self._bronze_queue is not None and self._bronze_drain_task is not None:
            with suppress(asyncio.QueueFull):
                self._bronze_queue.put_nowait(None)
            try:
                await asyncio.wait_for(
                    self._bronze_drain_task,
                    timeout=_BRONZE_DRAIN_TIMEOUT_SECS,
                )
            except TimeoutError:
                self._bronze_drain_task.cancel()
                with suppress(asyncio.CancelledError):
                    await self._bronze_drain_task

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
            id=self._recording_id,
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
        # Bronze enqueue is non-awaiting so capture stays off the I/O hot path.
        if self._bronze_queue is not None:
            try:
                self._bronze_queue.put_nowait(raw)
            except asyncio.QueueFull:
                _log.warning(
                    "bronze_queue_full_dropped",
                    event_type=raw.get("event_type"),
                    frame_url=raw.get("frame_url"),
                )
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

    # ----- bronze drain -----------------------------------------------------

    async def _drain_bronze(self) -> None:
        """Read envelopes off the bronze queue and batch-write them to bronze.

        Reads in batches of up to `_BRONZE_BATCH_SIZE` events with up to
        `_BRONZE_BATCH_WAIT_SECS` between successive items. A `None`
        sentinel terminates the loop. On `CancelledError` (overrun
        shutdown) the remaining queue contents are flushed best-effort.

        Bronze write failures are logged and swallowed — the drain task
        must not exit on a transient I/O hiccup, since the queue would
        then back up until `Recorder.stop()` returns.
        """
        queue = self._bronze_queue
        bronze = self._bronze
        recording_id = self._recording_id
        if queue is None or bronze is None:
            return

        async def flush(batch: list[dict[str, Any]]) -> None:
            if not batch:
                return
            try:
                await bronze.append_events(recording_id, batch)
            except Exception as exc:
                _log.error("bronze_drain_flush_failed", error=str(exc))

        try:
            while True:
                first = await queue.get()
                if first is None:
                    return
                batch: list[dict[str, Any]] = [first]
                deadline = asyncio.get_event_loop().time() + _BRONZE_BATCH_WAIT_SECS
                while len(batch) < _BRONZE_BATCH_SIZE:
                    remaining = deadline - asyncio.get_event_loop().time()
                    if remaining <= 0:
                        break
                    try:
                        item = await asyncio.wait_for(queue.get(), timeout=remaining)
                    except TimeoutError:
                        break
                    if item is None:
                        await flush(batch)
                        return
                    batch.append(item)
                await flush(batch)
        except asyncio.CancelledError:
            leftover: list[dict[str, Any]] = []
            while not queue.empty():
                try:
                    item = queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                if item is None:
                    continue
                leftover.append(item)
            if leftover:
                await flush(leftover)
            # Graceful shutdown: do not re-raise.

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
