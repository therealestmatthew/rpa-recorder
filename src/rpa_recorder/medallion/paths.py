"""Store-relative path layout for bronze artifacts.

These helpers are the only place the on-disk layout is encoded. Recorder,
executor, and the M11.5 silver-promotion worker all read paths from here so
moving a file requires changing exactly one function.

Paths use forward slashes only — `BronzeStore` implementations join them
under a backend-specific root, so callers stay backend-agnostic.
"""

from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from uuid import UUID

_ATTEMPT_EXT: Final[dict[str, str]] = {
    "screenshot": "png",
    "dom": "html",
    "a11y": "json",
}


def recording_dir(recording_id: UUID) -> str:
    """Directory containing all artifacts for one recording."""
    return f"recordings/{recording_id}/"


def recording_events_jsonl(recording_id: UUID) -> str:
    """Hot append-only line file for raw envelopes."""
    return f"recordings/{recording_id}/raw_events.jsonl"


def recording_events_parquet(recording_id: UUID) -> str:
    """Compacted Parquet form (written by M11.5 cron job)."""
    return f"recordings/{recording_id}/raw_events.parquet"


def recording_har(recording_id: UUID) -> str:
    """Full-recording network HAR."""
    return f"recordings/{recording_id}/network.har"


def recording_trace(recording_id: UUID) -> str:
    """Full-recording Playwright trace zip."""
    return f"recordings/{recording_id}/trace.zip"


def attempt_artifact(run_id: UUID, attempt_id: UUID, kind: str) -> str:
    """Per-attempt failure artifact (`screenshot` | `dom` | `a11y`)."""
    ext = _ATTEMPT_EXT.get(kind, "bin")
    return f"runs/{run_id}/attempts/{attempt_id}/{kind}.{ext}"


def llm_call(call_id: UUID) -> str:
    """Full LLM request + response JSON envelope."""
    return f"llm/{call_id}.json"


def review_audit_jsonl(recording_id: UUID) -> str:
    """Append-only audit log of confirmation decisions for a recording (M11)."""
    return f"reviews/{recording_id}/decisions.jsonl"


__all__ = [
    "attempt_artifact",
    "llm_call",
    "recording_dir",
    "recording_events_jsonl",
    "recording_events_parquet",
    "recording_har",
    "recording_trace",
    "review_audit_jsonl",
]
