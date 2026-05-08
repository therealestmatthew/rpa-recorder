"""Round-trip + Protocol-shape tests for the recovery package."""

from __future__ import annotations

from rpa_recorder.models import ElementSelector
from rpa_recorder.recovery import default_strategies
from rpa_recorder.recovery.protocol import RecoveryDecision


def test_recovery_decision_round_trips_via_pydantic() -> None:
    sel = ElementSelector(test_id="x")
    decision = RecoveryDecision(
        applicable=True,
        succeeded=True,
        new_selector=sel,
        rationale="ok",
        artifacts=["a/b"],
        duration_ms=42,
    )
    payload = decision.model_dump_json()
    rebuilt = RecoveryDecision.model_validate_json(payload)
    assert rebuilt == decision


def test_strategy_protocol_has_required_attrs() -> None:
    for strategy in default_strategies():
        assert isinstance(strategy.name, str) and strategy.name
        assert isinstance(strategy.applicable_modes, frozenset)
        assert isinstance(strategy.cost_tier, int)
        assert callable(strategy.attempt)


def test_default_strategies_sorted_by_cost_tier() -> None:
    tiers = [s.cost_tier for s in default_strategies()]
    assert tiers == sorted(tiers)
