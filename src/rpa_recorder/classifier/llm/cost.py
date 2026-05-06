"""Per-model token rates and a daily-budget guard.

`MODEL_RATES[model] -> (input_per_token_usd, output_per_token_usd)`. Unknown
models compute as $0 with a warning so a typo doesn't block the day.

`BudgetGuard` reads/writes today's spend either via Redis (distributed,
production) or a per-process dict (tests, local dev — logged once at startup
so a developer doesn't think they've spent more than they have).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

import structlog

from .protocol import LLMBudgetExceeded

if TYPE_CHECKING:
    from typing import Any

_log = structlog.get_logger(__name__)


# Per-token USD rates. Inputs are sticker prices for cache-miss tokens.
# Bumping a price → bump these. Bumping the model list → add a row.
MODEL_RATES: Final[dict[str, tuple[float, float]]] = {
    "claude-opus-4-7": (15.0e-6, 75.0e-6),
    "claude-opus-4-6": (15.0e-6, 75.0e-6),
    "claude-sonnet-4-6": (3.0e-6, 15.0e-6),
    "claude-sonnet-4-5": (3.0e-6, 15.0e-6),
    "claude-haiku-4-5-20251001": (1.0e-6, 5.0e-6),
}


def compute_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Return USD cost for one call. Unknown model → 0.0 with a one-line warning."""
    rates = MODEL_RATES.get(model)
    if rates is None:
        _log.warning("llm_cost_unknown_model", model=model)
        return 0.0
    in_rate, out_rate = rates
    return input_tokens * in_rate + output_tokens * out_rate


def _today_key() -> str:
    return f"spend:llm:{datetime.now(UTC).strftime('%Y-%m-%d')}"


class BudgetGuard:
    """Caps daily spend at `daily_budget_usd`. Distributed if `redis` provided.

    Without Redis the guard tracks spend in a per-process dict keyed by date.
    A single warning is logged on construction so callers know the budget is
    not shared across workers.
    """

    _warned_inmemory: bool = False

    def __init__(
        self,
        *,
        redis: Any | None = None,
        daily_budget_usd: float = 5.0,
        retention_days: int = 90,
    ) -> None:
        self._redis = redis
        self._cap = daily_budget_usd
        self._retention_s = retention_days * 86400
        self._mem: dict[str, float] = {}
        if redis is None and not BudgetGuard._warned_inmemory:
            _log.warning(
                "llm_budget_in_memory",
                detail="BudgetGuard has no Redis client; spend is tracked per-process only",
            )
            BudgetGuard._warned_inmemory = True

    async def current_spend(self) -> float:
        """Return today's spend in USD."""
        key = _today_key()
        if self._redis is None:
            return self._mem.get(key, 0.0)
        raw = await self._redis.get(key)
        if raw is None:
            return 0.0
        return float(raw)

    async def check_or_raise(self) -> None:
        """Raise `LLMBudgetExceeded` if today's spend already exceeds the cap."""
        spend = await self.current_spend()
        if spend >= self._cap:
            raise LLMBudgetExceeded(
                f"daily LLM budget ${self._cap:.2f} reached (spent ${spend:.4f})"
            )

    async def record_spend(self, usd: float) -> None:
        """Add `usd` to today's counter; refresh TTL on each write."""
        if usd <= 0:
            return
        key = _today_key()
        if self._redis is None:
            self._mem[key] = self._mem.get(key, 0.0) + usd
            return
        await self._redis.incrbyfloat(key, usd)
        await self._redis.expire(key, self._retention_s)


__all__ = ["MODEL_RATES", "BudgetGuard", "compute_cost"]
