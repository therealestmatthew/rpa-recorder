"""`ConfirmationRunner` — orchestrates a single `rpa confirm <id>` pass.

Per-decision persistence: each `ActionReviewResult` opens its own session
via the supplied `SessionFactory` so the session-context auto-commit makes
the partial update durable. Ctrl+C mid-pass keeps every decision so far.

Optional post-pass hook: when an ARQ pool is supplied, the runner enqueues
`promote_silver_to_gold` so dashboards reflect the new labels immediately.
M11.5 wires the pool; in M11 it stays None and the hook is a no-op.
"""

import time
from typing import TYPE_CHECKING, Any

import structlog

from rpa_recorder.cli.console import console
from rpa_recorder.config import Config
from rpa_recorder.confirmation.filters import default_filter
from rpa_recorder.confirmation.modes import default_mode
from rpa_recorder.confirmation.protocol import (
    ActionReviewResult,
    Decision,
    Filter,
    Renderer,
    ReviewMode,
    ReviewSummary,
)
from rpa_recorder.confirmation.renderers import default_renderer
from rpa_recorder.storage.repositories import RecordingRepository

if TYPE_CHECKING:
    from uuid import UUID

    from rpa_recorder.cli.dependencies import SessionFactory
    from rpa_recorder.medallion import BronzeWriter
    from rpa_recorder.models import RecordedAction, SemanticIntent


_log = structlog.get_logger(__name__)


class ConfirmationRunner:
    """Drives one confirmation pass for a single recording."""

    def __init__(
        self,
        *,
        filter: Filter,
        mode: ReviewMode,
        renderer: Renderer,
        session_factory: SessionFactory,
        threshold: float = 0.7,
        arq_pool: Any = None,
        bronze_writer: BronzeWriter | None = None,
        audit_bronze: bool = True,
    ) -> None:
        self._filter = filter
        self._mode = mode
        self._renderer = renderer
        self._session_factory = session_factory
        self._threshold = threshold
        self._arq_pool = arq_pool
        self._bronze_writer = bronze_writer
        self._audit_bronze = audit_bronze

    async def run(self, recording_id: UUID) -> ReviewSummary:
        """Load → filter → mode.review → summarize → optional enqueue."""
        started = time.monotonic()

        async with self._session_factory() as db:
            recording = await RecordingRepository(db).get(recording_id)
        if recording is None:
            msg = f"recording {recording_id} not found"
            raise LookupError(msg)

        candidates = self._filter.select(recording, threshold=self._threshold)
        if not candidates:
            summary = ReviewSummary(
                recording_id=recording_id,
                total_candidates=0,
                accepted=0,
                relabeled=0,
                skipped=0,
                duration_s=time.monotonic() - started,
            )
            console.print("[warning]Nothing to review.[/warning]")
            console.print(self._renderer.render_summary(summary))
            return summary

        results: list[ActionReviewResult] = []

        async def on_decision(result: ActionReviewResult) -> None:
            await self._persist(recording_id, candidates, result)
            results.append(result)

        try:
            await self._mode.review(
                candidates,
                renderer=self._renderer,
                on_decision=on_decision,
            )
        finally:
            summary = self._build_summary(
                recording_id=recording_id,
                total_candidates=len(candidates),
                results=results,
                duration_s=time.monotonic() - started,
            )
            console.print(self._renderer.render_summary(summary))

        await self._post_pass(recording_id)
        return summary

    async def _persist(
        self,
        recording_id: UUID,
        candidates: list[RecordedAction],
        result: ActionReviewResult,
    ) -> None:
        intent_to_set: SemanticIntent | None = None
        user_label: str | None = None
        if result.decision is Decision.ACCEPT:
            user_confirmed = True
        elif result.decision is Decision.RELABEL:
            user_confirmed = True
            if result.new_label is None:
                msg = "RELABEL decision missing new_label"
                raise ValueError(msg)
            intent_to_set = result.new_label
            user_label = result.new_label.value
        else:  # SKIP
            user_confirmed = False

        if result.decision is not Decision.SKIP:
            async with self._session_factory() as db:
                await RecordingRepository(db).update_action_classification(
                    result.action_id,
                    intent=intent_to_set,
                    user_confirmed=user_confirmed,
                    user_label=user_label,
                )

        _log.info(
            "confirmation_decision",
            recording_id=str(recording_id),
            action_id=str(result.action_id),
            decision=result.decision.value,
            new_label=result.new_label.value if result.new_label else None,
        )

        if self._bronze_writer is not None and self._audit_bronze:
            envelope = self._build_envelope(candidates, result)
            await self._bronze_writer.append_review_decision(recording_id, envelope)

    @staticmethod
    def _build_envelope(
        candidates: list[RecordedAction], result: ActionReviewResult
    ) -> dict[str, Any]:
        action = next((a for a in candidates if a.id == result.action_id), None)
        envelope: dict[str, Any] = {
            "action_id": str(result.action_id),
            "decision": result.decision.value,
            "new_label": result.new_label.value if result.new_label else None,
            "reviewed_at": result.reviewed_at.isoformat(),
        }
        if action is not None:
            envelope["classifier_intent"] = action.semantic_intent.value
            envelope["classifier_confidence"] = action.classification_confidence
        return envelope

    @staticmethod
    def _build_summary(
        *,
        recording_id: UUID,
        total_candidates: int,
        results: list[ActionReviewResult],
        duration_s: float,
    ) -> ReviewSummary:
        accepted = sum(1 for r in results if r.decision is Decision.ACCEPT)
        relabeled = sum(1 for r in results if r.decision is Decision.RELABEL)
        skipped = sum(1 for r in results if r.decision is Decision.SKIP)
        return ReviewSummary(
            recording_id=recording_id,
            total_candidates=total_candidates,
            accepted=accepted,
            relabeled=relabeled,
            skipped=skipped,
            duration_s=duration_s,
            results=results,
        )

    async def _post_pass(self, recording_id: UUID) -> None:
        if self._arq_pool is None:
            _log.info(
                "confirmation_post_pass_skipped",
                recording_id=str(recording_id),
                reason="no arq pool",
            )
            return
        try:
            await self._arq_pool.enqueue_job(
                "promote_silver_to_gold", recording_id=str(recording_id)
            )
        except Exception as exc:
            _log.warning(
                "confirmation_enqueue_failed",
                recording_id=str(recording_id),
                error=str(exc),
            )


def default_runner(
    *,
    session_factory: SessionFactory,
    threshold: float = 0.7,
    arq_pool: Any = None,
    bronze_writer: BronzeWriter | None = None,
    filter_name: str | None = None,
    filter_kwargs: dict[str, Any] | None = None,
    mode_name: str | None = None,
    mode_kwargs: dict[str, Any] | None = None,
    renderer_name: str | None = None,
    renderer_kwargs: dict[str, Any] | None = None,
) -> ConfirmationRunner:
    """Build a runner from registry names. Names default to Config values."""
    cfg = Config()
    selected_filter = default_filter(filter_name, **(filter_kwargs or {}))
    selected_mode = default_mode(mode_name, **(mode_kwargs or {}))
    selected_renderer = default_renderer(renderer_name, **(renderer_kwargs or {}))
    return ConfirmationRunner(
        filter=selected_filter,
        mode=selected_mode,
        renderer=selected_renderer,
        session_factory=session_factory,
        threshold=threshold,
        arq_pool=arq_pool,
        bronze_writer=bronze_writer,
        audit_bronze=cfg.confirmation_audit_bronze,
    )


__all__ = ["ConfirmationRunner", "default_runner"]
