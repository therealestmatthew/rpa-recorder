"""`IngestSession` (async) and `SyncIngestSession` (sync wrapper).

Lifecycle facade for hosts driving `rpa_recorder.integration` from the outside.
Owns the recording id, the bronze writer, the long-running DB session, and
optionally the heuristic classifier; ties them together so each ingested event
lands in JSONL + accumulates in memory, and `finalize()` runs the classifier
and persists the `Recording` aggregate to SQL.

Standard Selenium is synchronous, so `SyncIngestSession` runs an asyncio
event loop in a daemon thread and submits coroutines to it via
`asyncio.run_coroutine_threadsafe`. Hosts drive it with normal blocking calls.
"""

from __future__ import annotations

import asyncio
import threading
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Self
from uuid import UUID, uuid4

import structlog
from sqlalchemy.ext.asyncio import async_sessionmaker

from rpa_recorder.classifier.heuristic import default_pipeline
from rpa_recorder.config import Config
from rpa_recorder.integration.translator import SeleniumEventTranslator
from rpa_recorder.medallion.bronze import BronzeWriter
from rpa_recorder.medallion.bronze_store import LocalFilesystemStore
from rpa_recorder.models import RecordedAction, Recording
from rpa_recorder.storage.db import (
    Base,
    create_engine,
)
from rpa_recorder.storage.repositories import (
    BronzeArtifactRepository,
    RecordingRepository,
)

if TYPE_CHECKING:
    from collections.abc import Iterable
    from types import TracebackType

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

    from rpa_recorder.integration.events import SeleniumEvent

_log = structlog.get_logger(__name__)


class IngestSession:
    """Async ingest session for an external recorder.

    One instance per logical recording. Opens a long-running DB session at
    `create()` time, shares it across every bronze write so per-event commits
    are cheap, and commits + closes at `finalize()` / `__aexit__`.
    """

    def __init__(
        self,
        *,
        recording_id: UUID,
        name: str,
        starting_url: str,
        source_label: str,
        run_classifier: bool,
        config: Config,
        engine: AsyncEngine,
        session: AsyncSession,
        bronze_writer: BronzeWriter,
        recording_repo: RecordingRepository,
    ) -> None:
        self.recording_id = recording_id
        self._name = name
        self._starting_url = starting_url
        self._source_label = source_label
        self._run_classifier = run_classifier
        self._config = config
        self._engine = engine
        self._session = session
        self._bronze_writer = bronze_writer
        self._recording_repo = recording_repo
        self._translator = SeleniumEventTranslator()
        self._actions: list[RecordedAction] = []
        self._next_sequence = 0
        self._created_at: datetime = datetime.now(UTC)
        self._finalized = False
        self._owns_engine = True

    @classmethod
    async def create(
        cls,
        *,
        name: str,
        starting_url: str,
        recording_id: UUID | None = None,
        config: Config | None = None,
        source_label: str = "selenium",
        run_classifier: bool = True,
    ) -> Self:
        """Open the DB session, prepare bronze, return a session ready for ingest.

        `recording_id` defaults to a new UUID. `config` defaults to one loaded
        from `RPA_*` env vars. `source_label` is persisted on the
        `RecordingRow.source` column for medallion filtering.
        """
        cfg = config or Config()
        rec_id = recording_id or uuid4()

        engine = create_engine(cfg.database_url)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        factory = async_sessionmaker(engine, expire_on_commit=False)
        session = factory()

        store = LocalFilesystemStore(cfg.bronze_root)
        repo = BronzeArtifactRepository(session)
        writer = BronzeWriter(store, repo)
        recording_repo = RecordingRepository(session)

        return cls(
            recording_id=rec_id,
            name=name,
            starting_url=starting_url,
            source_label=source_label,
            run_classifier=run_classifier,
            config=cfg,
            engine=engine,
            session=session,
            bronze_writer=writer,
            recording_repo=recording_repo,
        )

    @property
    def actions(self) -> list[RecordedAction]:
        """Snapshot of `RecordedAction`s ingested so far."""
        return list(self._actions)

    async def ingest_event(self, event: SeleniumEvent) -> RecordedAction:
        """Translate one event, append to bronze, accumulate in memory."""
        action = self._translator.translate(event, sequence=self._next_sequence)
        self._next_sequence += 1
        self._actions.append(action)
        await self._bronze_writer.append_event(self.recording_id, action.model_dump(mode="json"))
        return action

    async def ingest_events(self, events: Iterable[SeleniumEvent]) -> list[RecordedAction]:
        """Translate + bronze-append a batch in one file open. Preferred for hot loops."""
        produced: list[RecordedAction] = []
        envelopes: list[dict[str, object]] = []
        for event in events:
            action = self._translator.translate(event, sequence=self._next_sequence)
            self._next_sequence += 1
            produced.append(action)
            envelopes.append(action.model_dump(mode="json"))
        self._actions.extend(produced)
        if envelopes:
            await self._bronze_writer.append_events(self.recording_id, envelopes)
        return produced

    async def finalize(self) -> Recording:
        """Run the classifier (if enabled), persist the `Recording`, return it."""
        if self._finalized:
            msg = f"IngestSession {self.recording_id} already finalized"
            raise RuntimeError(msg)

        actions = self._apply_classifier(self._actions) if self._run_classifier else self._actions

        recording = Recording(
            id=self.recording_id,
            name=self._name,
            created_at=self._created_at,
            starting_url=self._starting_url,
            actions=list(actions),
            source=self._source_label,
        )
        await self._recording_repo.save(recording)
        await self._bronze_writer.finalize_recording(
            self.recording_id,
            har_bytes=None,
            trace_bytes=None,
        )
        await self._session.commit()
        self._finalized = True
        return recording

    def _apply_classifier(self, actions: list[RecordedAction]) -> list[RecordedAction]:
        engine = default_pipeline()
        results = engine.process(list(actions))
        out: list[RecordedAction] = []
        for action, classification in results:
            out.append(
                action.model_copy(
                    update={
                        "semantic_intent": classification.intent,
                        "classification_confidence": classification.confidence,
                        "classification_reasoning": classification.reasoning,
                    },
                ),
            )
        return out

    async def aclose(self) -> None:
        """Close the DB session and dispose the engine. Idempotent."""
        try:
            await self._session.close()
        except Exception as exc:
            _log.error("ingest_session_close_failed", error=str(exc))
        if self._owns_engine:
            try:
                await self._engine.dispose()
            except Exception as exc:
                _log.error("ingest_engine_dispose_failed", error=str(exc))
            self._owns_engine = False

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if exc is None and not self._finalized:
            try:
                await self.finalize()
            except Exception as inner:
                _log.error("ingest_session_finalize_failed", error=str(inner))
                await self._session.rollback()
        elif exc is not None:
            await self._session.rollback()
        await self.aclose()


class SyncIngestSession:
    """Sync facade over `IngestSession` for synchronous hosts (e.g. Selenium).

    Runs a dedicated asyncio event loop in a daemon thread and submits each
    coroutine via `asyncio.run_coroutine_threadsafe`. The host sees a
    plain blocking API; the loop, engine, and DB session live for the
    lifetime of the wrapper.
    """

    def __init__(
        self,
        *,
        loop: asyncio.AbstractEventLoop,
        thread: threading.Thread,
        inner: IngestSession,
    ) -> None:
        self._loop = loop
        self._thread = thread
        self._inner = inner
        self._closed = False

    @property
    def recording_id(self) -> UUID:
        return self._inner.recording_id

    @property
    def actions(self) -> list[RecordedAction]:
        return self._inner.actions

    @classmethod
    def create(
        cls,
        *,
        name: str,
        starting_url: str,
        recording_id: UUID | None = None,
        config: Config | None = None,
        source_label: str = "selenium",
        run_classifier: bool = True,
    ) -> Self:
        loop = asyncio.new_event_loop()
        ready = threading.Event()

        def _run() -> None:
            asyncio.set_event_loop(loop)
            ready.set()
            loop.run_forever()

        thread = threading.Thread(target=_run, name="rpa-ingest-loop", daemon=True)
        thread.start()
        ready.wait()

        future = asyncio.run_coroutine_threadsafe(
            IngestSession.create(
                name=name,
                starting_url=starting_url,
                recording_id=recording_id,
                config=config,
                source_label=source_label,
                run_classifier=run_classifier,
            ),
            loop,
        )
        try:
            inner = future.result()
        except BaseException:
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=5.0)
            loop.close()
            raise

        return cls(loop=loop, thread=thread, inner=inner)

    def ingest_event(self, event: SeleniumEvent) -> RecordedAction:
        return asyncio.run_coroutine_threadsafe(
            self._inner.ingest_event(event),
            self._loop,
        ).result()

    def ingest_events(self, events: Iterable[SeleniumEvent]) -> list[RecordedAction]:
        return asyncio.run_coroutine_threadsafe(
            self._inner.ingest_events(events),
            self._loop,
        ).result()

    def finalize(self) -> Recording:
        async def _finalize_and_close() -> Recording:
            try:
                return await self._inner.finalize()
            finally:
                await self._inner.aclose()

        try:
            return asyncio.run_coroutine_threadsafe(
                _finalize_and_close(),
                self._loop,
            ).result()
        finally:
            self._shutdown()

    def close(self) -> None:
        """Best-effort cleanup. Idempotent. Skips finalize."""
        if self._closed:
            return
        try:
            asyncio.run_coroutine_threadsafe(
                self._inner.aclose(),
                self._loop,
            ).result(timeout=5.0)
        except Exception as exc:
            _log.error("sync_ingest_close_failed", error=str(exc))
        finally:
            self._shutdown()

    def _shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5.0)
        try:
            self._loop.close()
        except Exception as exc:
            _log.error("sync_ingest_loop_close_failed", error=str(exc))

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._closed:
            return
        if exc is None:
            try:
                self.finalize()
            except Exception as inner:
                _log.error("sync_ingest_finalize_failed", error=str(inner))
                self.close()
        else:
            self.close()


__all__ = ["IngestSession", "SyncIngestSession"]
