"""`BronzeWriter` — high-level writes to bronze through a `BronzeStore`.

Routes raw recorder envelopes (JSONL append), executor failure artifacts
(screenshot / DOM / a11y), HAR + trace finalization, and LLM call dumps
into the bronze layer. Registers a `bronze_artifacts` pointer row for each
persisted artifact via `BronzeArtifactRepository`.

Best-effort policy: every write catches exceptions and logs via
`structlog.error(...)`. Recording / replay must never fail because bronze
is unhappy, so callers can rely on "this returns" without try/except.
"""

import json
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID, uuid4

import structlog

from rpa_recorder.medallion import paths

if TYPE_CHECKING:
    from rpa_recorder.medallion.bronze_store import BronzeStore
    from rpa_recorder.storage.repositories import BronzeArtifactRepository

_log = structlog.get_logger(__name__)


class BronzeWriter:
    """High-level bronze writer used by recorder + executor + LLM clients."""

    def __init__(
        self,
        store: BronzeStore,
        repo: BronzeArtifactRepository,
    ) -> None:
        self._store = store
        self._repo = repo
        self._registered_jsonl: set[UUID] = set()
        self._registered_reviews: set[UUID] = set()

    async def append_event(self, recording_id: UUID, envelope: dict[str, Any]) -> None:
        """Append a single envelope. Convenience wrapper over `append_events`."""
        await self.append_events(recording_id, [envelope])

    async def append_events(self, recording_id: UUID, envelopes: list[dict[str, Any]]) -> None:
        """Append a batch of envelopes in one file open. Empty list is a no-op."""
        if not envelopes:
            return
        path = paths.recording_events_jsonl(recording_id)
        try:
            await self._store.append_lines(path, [json.dumps(e) for e in envelopes])
        except Exception as exc:
            _log.error(
                "bronze_append_events_failed",
                recording_id=str(recording_id),
                error=str(exc),
            )
            return
        if recording_id not in self._registered_jsonl:
            try:
                await self._repo.add(
                    artifact_id=str(uuid4()),
                    kind="event_jsonl",
                    path=path,
                    sha256="",
                    size_bytes=0,
                    recording_id=str(recording_id),
                )
                self._registered_jsonl.add(recording_id)
            except Exception as exc:
                _log.error(
                    "bronze_register_jsonl_failed",
                    recording_id=str(recording_id),
                    error=str(exc),
                )

    async def finalize_recording(
        self,
        recording_id: UUID,
        har_bytes: bytes | None,
        trace_bytes: bytes | None,
    ) -> None:
        """Land HAR + trace into bronze and refresh the JSONL pointer row.

        The JSONL pointer was inserted with empty `sha256` and `size_bytes=0`
        on first append; this method updates it with the final on-disk values.
        """
        jsonl_path = paths.recording_events_jsonl(recording_id)
        try:
            size, sha = await self._store.stat(jsonl_path)
            await self._repo.update_size_and_sha(
                path=jsonl_path,
                sha256=sha,
                size_bytes=size,
            )
        except Exception as exc:
            _log.error(
                "bronze_jsonl_stat_failed",
                recording_id=str(recording_id),
                error=str(exc),
            )

        if har_bytes is not None:
            await self._write_artifact(
                kind="har",
                path=paths.recording_har(recording_id),
                data=har_bytes,
                recording_id=str(recording_id),
            )
        if trace_bytes is not None:
            await self._write_artifact(
                kind="trace",
                path=paths.recording_trace(recording_id),
                data=trace_bytes,
                recording_id=str(recording_id),
            )

    async def write_attempt_artifact(
        self,
        run_id: UUID,
        attempt_id: UUID,
        kind: Literal["screenshot", "dom", "a11y"],
        data: bytes,
    ) -> str:
        """Write a per-attempt failure artifact. Returns the store-relative path."""
        path = paths.attempt_artifact(run_id, attempt_id, kind)
        await self._write_artifact(
            kind=kind,
            path=path,
            data=data,
            run_id=str(run_id),
            attempt_id=str(attempt_id),
        )
        return path

    async def append_review_decision(self, recording_id: UUID, envelope: dict[str, Any]) -> None:
        """Append one confirmation decision to reviews/<rec>/decisions.jsonl (M11).

        Best-effort: catches exceptions and logs via structlog. Confirmation
        flow must never fail because bronze is unhappy.
        """
        path = paths.review_audit_jsonl(recording_id)
        try:
            await self._store.append_lines(path, [json.dumps(envelope)])
        except Exception as exc:
            _log.error(
                "bronze_append_review_failed",
                recording_id=str(recording_id),
                error=str(exc),
            )
            return
        if recording_id not in self._registered_reviews:
            try:
                await self._repo.add(
                    artifact_id=str(uuid4()),
                    kind="review_audit_jsonl",
                    path=path,
                    sha256="",
                    size_bytes=0,
                    recording_id=str(recording_id),
                )
                self._registered_reviews.add(recording_id)
            except Exception as exc:
                _log.error(
                    "bronze_register_review_failed",
                    recording_id=str(recording_id),
                    error=str(exc),
                )

    async def write_llm_call(self, call_id: UUID, payload: dict[str, Any]) -> str:
        """Persist the full request + response JSON for one Anthropic call."""
        path = paths.llm_call(call_id)
        data = json.dumps(payload).encode("utf-8")
        await self._write_artifact(kind="llm_call", path=path, data=data)
        return path

    async def _write_artifact(
        self,
        *,
        kind: str,
        path: str,
        data: bytes,
        recording_id: str | None = None,
        run_id: str | None = None,
        attempt_id: str | None = None,
    ) -> None:
        try:
            sha = await self._store.put(path, data)
        except Exception as exc:
            _log.error("bronze_put_failed", path=path, kind=kind, error=str(exc))
            return
        try:
            await self._repo.add(
                artifact_id=str(uuid4()),
                kind=kind,
                path=path,
                sha256=sha,
                size_bytes=len(data),
                recording_id=recording_id,
                run_id=run_id,
                attempt_id=attempt_id,
            )
        except Exception as exc:
            _log.error("bronze_register_failed", path=path, kind=kind, error=str(exc))


__all__ = ["BronzeWriter"]
