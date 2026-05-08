"""Tests for the M11 ConfirmationRunner orchestrator."""

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import pytest

from rpa_recorder.confirmation import (
    ActionReviewResult,
    ConfirmationRunner,
    Decision,
    Renderer,
)
from rpa_recorder.confirmation.renderers import CompactRenderer
from rpa_recorder.confirmation.runner import default_runner
from rpa_recorder.models import (
    ActionType,
    ClickPayload,
    RecordedAction,
    Recording,
    SemanticIntent,
)
from rpa_recorder.storage.db import create_engine, get_session, init_db
from rpa_recorder.storage.repositories import RecordingRepository

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

    from sqlalchemy.ext.asyncio import AsyncEngine


@pytest.fixture
def engine() -> Iterator[AsyncEngine]:
    """Fresh in-memory engine per test, schema applied."""
    eng = create_engine("sqlite+aiosqlite:///:memory:")
    asyncio.run(init_db(eng))
    yield eng
    asyncio.run(eng.dispose())


def _make_recording(
    *,
    actions: list[RecordedAction] | None = None,
) -> Recording:
    return Recording(
        id=uuid4(),
        name="t",
        created_at=datetime(2026, 5, 6, tzinfo=UTC),
        starting_url="https://example.com",
        actions=actions
        or [
            RecordedAction(
                sequence=0,
                timestamp=datetime(2026, 5, 6, tzinfo=UTC),
                action_type=ActionType.CLICK,
                payload=ClickPayload(),
                url="https://example.com",
                classification_confidence=0.5,
            ),
            RecordedAction(
                sequence=1,
                timestamp=datetime(2026, 5, 6, tzinfo=UTC),
                action_type=ActionType.CLICK,
                payload=ClickPayload(),
                url="https://example.com",
                classification_confidence=0.6,
            ),
            RecordedAction(
                sequence=2,
                timestamp=datetime(2026, 5, 6, tzinfo=UTC),
                action_type=ActionType.CLICK,
                payload=ClickPayload(),
                url="https://example.com",
                classification_confidence=0.95,
            ),
        ],
    )


def _make_session_factory(eng: Any) -> Any:
    def factory() -> Any:
        return get_session(eng)

    return factory


async def _seed(eng: Any, recording: Recording) -> None:
    async with get_session(eng) as db:
        await RecordingRepository(db).save(recording)


class _ScriptedMode:
    """Test-only mode that replays a precomputed list of decisions."""

    name = "scripted"

    def __init__(self, results: list[ActionReviewResult]) -> None:
        self._results = results

    async def review(
        self,
        candidates: list[RecordedAction],
        *,
        renderer: Renderer,
        on_decision: Any,
    ) -> list[ActionReviewResult]:
        del candidates, renderer
        for r in self._results:
            await on_decision(r)
        return list(self._results)


class _AcceptAllFilter:
    name = "accept_all"

    def select(self, recording: Recording, *, threshold: float) -> list[RecordedAction]:
        del threshold
        return list(recording.actions)


def _result(
    action_id: UUID, decision: Decision, label: SemanticIntent | None = None
) -> ActionReviewResult:
    return ActionReviewResult(
        action_id=action_id,
        decision=decision,
        new_label=label,
        reviewed_at=datetime(2026, 5, 6, tzinfo=UTC),
    )


async def test_runner_returns_summary_with_correct_totals(
    engine: AsyncEngine,
) -> None:
    rec = _make_recording()
    await _seed(engine, rec)
    sf = _make_session_factory(engine)
    scripted = [
        _result(rec.actions[0].id, Decision.ACCEPT),
        _result(rec.actions[1].id, Decision.RELABEL, SemanticIntent.SEARCH),
        _result(rec.actions[2].id, Decision.SKIP),
    ]
    runner = ConfirmationRunner(
        filter=_AcceptAllFilter(),
        mode=_ScriptedMode(scripted),
        renderer=CompactRenderer(),
        session_factory=sf,
    )
    summary = await runner.run(rec.id)
    assert summary.total_candidates == 3
    assert summary.accepted == 1
    assert summary.relabeled == 1
    assert summary.skipped == 1
    assert len(summary.results) == 3


async def test_runner_persists_each_decision_incrementally(
    engine: AsyncEngine,
) -> None:
    rec = _make_recording()
    await _seed(engine, rec)
    sf = _make_session_factory(engine)
    runner = ConfirmationRunner(
        filter=_AcceptAllFilter(),
        mode=_ScriptedMode(
            [
                _result(rec.actions[0].id, Decision.ACCEPT),
                _result(rec.actions[1].id, Decision.RELABEL, SemanticIntent.LOGIN),
                _result(rec.actions[2].id, Decision.SKIP),
            ]
        ),
        renderer=CompactRenderer(),
        session_factory=sf,
    )
    await runner.run(rec.id)

    async with get_session(engine) as db:
        reloaded = await RecordingRepository(db).get(rec.id)
    assert reloaded is not None
    by_seq = {a.sequence: a for a in reloaded.actions}
    assert by_seq[0].user_confirmed is True
    assert by_seq[1].user_confirmed is True
    assert by_seq[1].user_label == "login"
    assert by_seq[1].semantic_intent is SemanticIntent.LOGIN
    assert by_seq[2].user_confirmed is False  # skipped


async def test_runner_returns_empty_summary_when_filter_yields_nothing(
    engine: AsyncEngine,
) -> None:
    rec = _make_recording()
    await _seed(engine, rec)
    sf = _make_session_factory(engine)

    class _NoneFilter:
        name = "none"

        def select(self, recording: Recording, *, threshold: float) -> list[RecordedAction]:
            del recording, threshold
            return []

    runner = ConfirmationRunner(
        filter=_NoneFilter(),
        mode=_ScriptedMode([]),
        renderer=CompactRenderer(),
        session_factory=sf,
    )
    summary = await runner.run(rec.id)
    assert summary.total_candidates == 0
    assert summary.accepted == 0


async def test_runner_raises_on_unknown_recording(
    engine: AsyncEngine,
) -> None:
    sf = _make_session_factory(engine)
    runner = ConfirmationRunner(
        filter=_AcceptAllFilter(),
        mode=_ScriptedMode([]),
        renderer=CompactRenderer(),
        session_factory=sf,
    )
    with pytest.raises(LookupError):
        await runner.run(uuid4())


class _StubArqPool:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def enqueue_job(self, name: str, **kwargs: Any) -> None:
        self.calls.append((name, kwargs))


async def test_runner_enqueues_promote_silver_to_gold_when_pool_provided(
    engine: AsyncEngine,
) -> None:
    rec = _make_recording()
    await _seed(engine, rec)
    sf = _make_session_factory(engine)
    pool = _StubArqPool()
    runner = ConfirmationRunner(
        filter=_AcceptAllFilter(),
        mode=_ScriptedMode([_result(rec.actions[0].id, Decision.ACCEPT)]),
        renderer=CompactRenderer(),
        session_factory=sf,
        arq_pool=pool,
    )
    await runner.run(rec.id)
    assert pool.calls == [
        ("promote_silver_to_gold", {"recording_id": str(rec.id)}),
    ]


async def test_runner_skips_enqueue_when_no_pool(
    engine: AsyncEngine,
) -> None:
    rec = _make_recording()
    await _seed(engine, rec)
    sf = _make_session_factory(engine)
    runner = ConfirmationRunner(
        filter=_AcceptAllFilter(),
        mode=_ScriptedMode([_result(rec.actions[0].id, Decision.ACCEPT)]),
        renderer=CompactRenderer(),
        session_factory=sf,
    )
    # Just assert no exception; structlog log line is the no-op.
    await runner.run(rec.id)


class _StubBronzeWriter:
    def __init__(self) -> None:
        self.envelopes: list[tuple[UUID, dict[str, Any]]] = []

    async def append_review_decision(self, recording_id: UUID, envelope: dict[str, Any]) -> None:
        self.envelopes.append((recording_id, envelope))


async def test_runner_writes_bronze_audit_when_enabled(
    engine: AsyncEngine,
) -> None:
    rec = _make_recording()
    await _seed(engine, rec)
    sf = _make_session_factory(engine)
    writer = _StubBronzeWriter()
    runner = ConfirmationRunner(
        filter=_AcceptAllFilter(),
        mode=_ScriptedMode(
            [
                _result(rec.actions[0].id, Decision.ACCEPT),
                _result(rec.actions[1].id, Decision.SKIP),
            ]
        ),
        renderer=CompactRenderer(),
        session_factory=sf,
        bronze_writer=writer,  # type: ignore[arg-type]
        audit_bronze=True,
    )
    await runner.run(rec.id)
    assert len(writer.envelopes) == 2
    rec_id, first = writer.envelopes[0]
    assert rec_id == rec.id
    assert first["decision"] == "accept"
    assert "classifier_intent" in first
    assert "classifier_confidence" in first


async def test_runner_skips_bronze_when_audit_disabled(
    engine: AsyncEngine,
) -> None:
    rec = _make_recording()
    await _seed(engine, rec)
    sf = _make_session_factory(engine)
    writer = _StubBronzeWriter()
    runner = ConfirmationRunner(
        filter=_AcceptAllFilter(),
        mode=_ScriptedMode([_result(rec.actions[0].id, Decision.ACCEPT)]),
        renderer=CompactRenderer(),
        session_factory=sf,
        bronze_writer=writer,  # type: ignore[arg-type]
        audit_bronze=False,
    )
    await runner.run(rec.id)
    assert writer.envelopes == []


async def test_runner_propagates_partial_summary_on_mode_exception(
    engine: AsyncEngine,
) -> None:
    rec = _make_recording()
    await _seed(engine, rec)
    sf = _make_session_factory(engine)

    class _RaisingMode:
        name = "raising"

        async def review(
            self,
            candidates: list[RecordedAction],
            *,
            renderer: Renderer,
            on_decision: Any,
        ) -> list[ActionReviewResult]:
            del renderer
            await on_decision(_result(candidates[0].id, Decision.ACCEPT))
            msg = "user interrupt"
            raise KeyboardInterrupt(msg)

    runner = ConfirmationRunner(
        filter=_AcceptAllFilter(),
        mode=_RaisingMode(),
        renderer=CompactRenderer(),
        session_factory=sf,
    )
    with pytest.raises(KeyboardInterrupt):
        await runner.run(rec.id)

    # Despite the interrupt, the first decision must have persisted.
    async with get_session(engine) as db:
        reloaded = await RecordingRepository(db).get(rec.id)
    assert reloaded is not None
    assert reloaded.actions[0].user_confirmed is True


def test_default_runner_constructs_with_registry_names() -> None:
    @asynccontextmanager
    async def _empty() -> AsyncIterator[Any]:
        yield None

    def _factory() -> Any:
        return _empty()

    runner = default_runner(session_factory=_factory)
    assert isinstance(runner, ConfirmationRunner)
