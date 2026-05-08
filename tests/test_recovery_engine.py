"""Engine orchestration tests with a fake Page + fake strategies."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from rpa_recorder.config import Config
from rpa_recorder.models import (
    ActionExecution,
    ActionType,
    ClickPayload,
    ElementSelector,
    ExecutionAttempt,
    ExecutionStatus,
    FailureMode,
    RecordedAction,
)
from rpa_recorder.recovery.engine import RecoveryEngine
from rpa_recorder.recovery.protocol import RecoveryContext, RecoveryDecision


class _FakePage:
    """Stand-in for `playwright.async_api.Page`. Engine only uses it for verifier calls."""

    def __init__(self, *, verify_ok: bool = True) -> None:
        self._verify_ok = verify_ok
        self.frames: list[Any] = []
        self.main_frame: Any = None

    async def content(self) -> str:
        return "<html></html>"


class _RecordingStrategy:
    def __init__(
        self,
        name: str,
        *,
        applicable_modes: frozenset[FailureMode],
        cost_tier: int,
        decision: RecoveryDecision,
        sleep_s: float = 0.0,
    ) -> None:
        self.name = name
        self.applicable_modes = applicable_modes
        self.cost_tier = cost_tier
        self.calls = 0
        self._decision = decision
        self._sleep_s = sleep_s

    async def attempt(
        self,
        *,
        failed: ActionExecution,
        page: Any,
        original: RecordedAction,
        ctx: RecoveryContext,
    ) -> RecoveryDecision:
        self.calls += 1
        if self._sleep_s:
            await asyncio.sleep(self._sleep_s)
        return self._decision


@pytest.fixture
def click_action() -> RecordedAction:
    return RecordedAction(
        sequence=1,
        timestamp=datetime.now(UTC),
        action_type=ActionType.CLICK,
        payload=ClickPayload(),
        selector=ElementSelector(test_id="save"),
        url="https://example.com",
    )


def _failed(failure_mode: FailureMode) -> ActionExecution:
    attempt = ExecutionAttempt(
        attempt_number=1,
        started_at=datetime.now(UTC),
        ended_at=datetime.now(UTC),
        status=ExecutionStatus.FAILED,
        failure_mode=failure_mode,
        error_message="boom",
    )
    return ActionExecution(
        action_id=uuid4(),
        status=ExecutionStatus.FAILED,
        attempts=[attempt],
    )


@pytest.fixture
def engine_config(tmp_path: Any) -> Config:
    return Config(recovery_strategy_timeout_s=1.0, recovery_llm_timeout_s=2.0)


def _ok(rationale: str = "ok") -> RecoveryDecision:
    return RecoveryDecision(applicable=True, succeeded=True, rationale=rationale, duration_ms=1)


def _skip() -> RecoveryDecision:
    return RecoveryDecision(applicable=False, succeeded=False, rationale="n/a", duration_ms=1)


def _fail() -> RecoveryDecision:
    return RecoveryDecision(applicable=True, succeeded=False, rationale="bad", duration_ms=1)


async def test_engine_filters_by_applicable_modes(
    click_action: RecordedAction,
    engine_config: Config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(RecoveryEngine, "_verify", _always_verify_ok, raising=True)
    timeout_only = _RecordingStrategy(
        "timeout_only",
        applicable_modes=frozenset({FailureMode.TIMEOUT}),
        cost_tier=0,
        decision=_ok(),
    )
    notfound_only = _RecordingStrategy(
        "notfound_only",
        applicable_modes=frozenset({FailureMode.ELEMENT_NOT_FOUND}),
        cost_tier=0,
        decision=_ok(),
    )
    engine = RecoveryEngine([timeout_only, notfound_only], config=engine_config)
    result = await engine.attempt(
        failed=_failed(FailureMode.TIMEOUT),
        page=_FakePage(),  # type: ignore[arg-type]
        original=click_action,
        ctx=RecoveryContext(),
    )
    assert result is not None
    assert result.strategy == "timeout_only"
    assert timeout_only.calls == 1
    assert notfound_only.calls == 0


async def test_engine_runs_in_cost_tier_order(
    click_action: RecordedAction,
    engine_config: Config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(RecoveryEngine, "_verify", _always_verify_ok, raising=True)
    cheap = _RecordingStrategy(
        "cheap",
        applicable_modes=frozenset({FailureMode.ELEMENT_NOT_INTERACTABLE}),
        cost_tier=0,
        decision=_fail(),
    )
    mid = _RecordingStrategy(
        "mid",
        applicable_modes=frozenset({FailureMode.ELEMENT_NOT_INTERACTABLE}),
        cost_tier=2,
        decision=_ok(),
    )
    expensive = _RecordingStrategy(
        "expensive",
        applicable_modes=frozenset({FailureMode.ELEMENT_NOT_INTERACTABLE}),
        cost_tier=5,
        decision=_ok(),
    )
    # Provide them out of order; engine must re-sort.
    engine = RecoveryEngine([expensive, cheap, mid], config=engine_config)
    result = await engine.attempt(
        failed=_failed(FailureMode.ELEMENT_NOT_INTERACTABLE),
        page=_FakePage(),  # type: ignore[arg-type]
        original=click_action,
        ctx=RecoveryContext(),
    )
    assert result is not None
    assert result.strategy == "mid"
    assert cheap.calls == 1
    assert mid.calls == 1
    assert expensive.calls == 0


async def test_engine_stops_on_first_verified_success(
    click_action: RecordedAction,
    engine_config: Config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(RecoveryEngine, "_verify", _always_verify_ok, raising=True)
    first = _RecordingStrategy(
        "first",
        applicable_modes=frozenset({FailureMode.ELEMENT_NOT_INTERACTABLE}),
        cost_tier=0,
        decision=_ok(),
    )
    second = _RecordingStrategy(
        "second",
        applicable_modes=frozenset({FailureMode.ELEMENT_NOT_INTERACTABLE}),
        cost_tier=1,
        decision=_ok(),
    )
    engine = RecoveryEngine([first, second], config=engine_config)
    result = await engine.attempt(
        failed=_failed(FailureMode.ELEMENT_NOT_INTERACTABLE),
        page=_FakePage(),  # type: ignore[arg-type]
        original=click_action,
        ctx=RecoveryContext(),
    )
    assert result is not None
    assert result.strategy == "first"
    assert second.calls == 0


async def test_engine_skips_strategy_if_verifier_rejects(
    click_action: RecordedAction,
    engine_config: Config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"verify": 0}

    async def _verifier(self: RecoveryEngine, page: Any, sel: ElementSelector) -> bool:
        calls["verify"] += 1
        return calls["verify"] > 1  # first call rejects, second accepts

    monkeypatch.setattr(RecoveryEngine, "_verify", _verifier, raising=True)
    first = _RecordingStrategy(
        "first",
        applicable_modes=frozenset({FailureMode.ELEMENT_NOT_INTERACTABLE}),
        cost_tier=0,
        decision=_ok("first claims ok"),
    )
    second = _RecordingStrategy(
        "second",
        applicable_modes=frozenset({FailureMode.ELEMENT_NOT_INTERACTABLE}),
        cost_tier=1,
        decision=_ok("second claims ok"),
    )
    engine = RecoveryEngine([first, second], config=engine_config)
    result = await engine.attempt(
        failed=_failed(FailureMode.ELEMENT_NOT_INTERACTABLE),
        page=_FakePage(),  # type: ignore[arg-type]
        original=click_action,
        ctx=RecoveryContext(),
    )
    assert result is not None
    assert result.strategy == "second"
    assert first.calls == 1
    assert second.calls == 1


async def test_engine_per_strategy_timeout_caps_runtime(
    click_action: RecordedAction,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(RecoveryEngine, "_verify", _always_verify_ok, raising=True)
    slow = _RecordingStrategy(
        "slow",
        applicable_modes=frozenset({FailureMode.TIMEOUT}),
        cost_tier=0,
        decision=_ok(),
        sleep_s=10.0,
    )
    fallback = _RecordingStrategy(
        "fallback",
        applicable_modes=frozenset({FailureMode.TIMEOUT}),
        cost_tier=1,
        decision=_ok(),
    )
    engine = RecoveryEngine(
        [slow, fallback],
        config=Config(recovery_strategy_timeout_s=0.05),
    )
    result = await engine.attempt(
        failed=_failed(FailureMode.TIMEOUT),
        page=_FakePage(),  # type: ignore[arg-type]
        original=click_action,
        ctx=RecoveryContext(),
    )
    assert result is not None
    assert result.strategy == "fallback"


async def test_engine_returns_none_when_all_strategies_fail(
    click_action: RecordedAction,
    engine_config: Config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(RecoveryEngine, "_verify", _always_verify_ok, raising=True)
    a = _RecordingStrategy(
        "a",
        applicable_modes=frozenset({FailureMode.TIMEOUT}),
        cost_tier=0,
        decision=_skip(),
    )
    b = _RecordingStrategy(
        "b",
        applicable_modes=frozenset({FailureMode.TIMEOUT}),
        cost_tier=1,
        decision=_fail(),
    )
    engine = RecoveryEngine([a, b], config=engine_config)
    result = await engine.attempt(
        failed=_failed(FailureMode.TIMEOUT),
        page=_FakePage(),  # type: ignore[arg-type]
        original=click_action,
        ctx=RecoveryContext(),
    )
    assert result is None


async def test_engine_respects_max_depth(
    click_action: RecordedAction,
    engine_config: Config,
) -> None:
    # depth >= ctx.max_depth → returns None without invoking strategies.
    invoked = _RecordingStrategy(
        "invoked",
        applicable_modes=frozenset({FailureMode.TIMEOUT}),
        cost_tier=0,
        decision=_ok(),
    )
    engine = RecoveryEngine([invoked], config=engine_config)
    result = await engine.attempt(
        failed=_failed(FailureMode.TIMEOUT),
        page=_FakePage(),  # type: ignore[arg-type]
        original=click_action,
        ctx=RecoveryContext(max_depth=1),
        depth=1,
    )
    assert result is None
    assert invoked.calls == 0


async def test_engine_emits_events_when_emitter_provided(
    click_action: RecordedAction,
    engine_config: Config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(RecoveryEngine, "_verify", _always_verify_ok, raising=True)
    events: list[tuple[str, dict[str, Any]]] = []

    async def emit(name: str, payload: dict[str, Any]) -> None:
        events.append((name, payload))

    strategy = _RecordingStrategy(
        "go",
        applicable_modes=frozenset({FailureMode.TIMEOUT}),
        cost_tier=0,
        decision=_ok(),
    )
    engine = RecoveryEngine([strategy], config=engine_config, event_emitter=emit)
    await engine.attempt(
        failed=_failed(FailureMode.TIMEOUT),
        page=_FakePage(),  # type: ignore[arg-type]
        original=click_action,
        ctx=RecoveryContext(),
    )
    names = [name for name, _ in events]
    assert "recovery_started" in names
    assert "recovery_succeeded" in names


async def test_engine_short_circuits_when_no_failure_mode(
    click_action: RecordedAction,
    engine_config: Config,
) -> None:
    incomplete = ActionExecution(
        action_id=uuid4(),
        status=ExecutionStatus.FAILED,
        attempts=[
            ExecutionAttempt(
                attempt_number=1,
                started_at=datetime.now(UTC),
                ended_at=datetime.now(UTC),
                status=ExecutionStatus.FAILED,
            )
        ],
    )
    engine = RecoveryEngine([], config=engine_config)
    result = await engine.attempt(
        failed=incomplete,
        page=_FakePage(),  # type: ignore[arg-type]
        original=click_action,
        ctx=RecoveryContext(),
    )
    assert result is None


async def _always_verify_ok(self: RecoveryEngine, page: Any, sel: ElementSelector) -> bool:
    return True
