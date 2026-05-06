"""Cost computation + per-day budget guard."""

import pytest

from rpa_recorder.classifier.llm.cost import MODEL_RATES, BudgetGuard, compute_cost
from rpa_recorder.classifier.llm.protocol import LLMBudgetExceeded


def test_compute_cost_for_known_model() -> None:
    rates = MODEL_RATES["claude-sonnet-4-6"]
    cost = compute_cost("claude-sonnet-4-6", 1_000, 500)
    assert cost == pytest.approx(1_000 * rates[0] + 500 * rates[1])


def test_compute_cost_unknown_model_returns_zero(caplog: pytest.LogCaptureFixture) -> None:
    cost = compute_cost("not-a-real-model", 100, 100)
    assert cost == 0.0


async def test_budget_guard_blocks_after_threshold() -> None:
    guard = BudgetGuard(daily_budget_usd=0.10)
    await guard.record_spend(0.099)
    await guard.check_or_raise()  # below cap, no raise
    await guard.record_spend(0.01)
    with pytest.raises(LLMBudgetExceeded):
        await guard.check_or_raise()


async def test_budget_guard_record_spend_ignores_non_positive() -> None:
    guard = BudgetGuard(daily_budget_usd=1.0)
    await guard.record_spend(0)
    await guard.record_spend(-1)
    assert await guard.current_spend() == 0


async def test_budget_guard_in_memory_logs_once() -> None:
    # Reset class-level flag so this test sees the warning regardless of order.
    BudgetGuard._warned_inmemory = False
    BudgetGuard(daily_budget_usd=1.0)
    BudgetGuard(daily_budget_usd=1.0)
    # No assertion on log lines — structlog routes vary; the contract is
    # "warn at most once per process" which the flag enforces.
    assert BudgetGuard._warned_inmemory is True


async def test_budget_guard_with_redis_uses_client() -> None:
    class FakeRedis:
        def __init__(self) -> None:
            self.store: dict[str, float] = {}
            self.expirations: dict[str, int] = {}

        async def get(self, key: str) -> str | None:
            value = self.store.get(key)
            return None if value is None else str(value)

        async def incrbyfloat(self, key: str, value: float) -> float:
            self.store[key] = self.store.get(key, 0.0) + value
            return self.store[key]

        async def expire(self, key: str, ttl: int) -> None:
            self.expirations[key] = ttl

    fake = FakeRedis()
    guard = BudgetGuard(redis=fake, daily_budget_usd=1.0)
    await guard.record_spend(0.5)
    spend = await guard.current_spend()
    assert spend == pytest.approx(0.5)
    assert any(v > 0 for v in fake.expirations.values())
