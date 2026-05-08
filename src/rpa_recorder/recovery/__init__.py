"""Modular recovery engine — wait / scroll / modal / frame / LLM-reselect.

Public API:

    from rpa_recorder.recovery import default_engine, RecoveryContext

    engine = default_engine()
    ctx = RecoveryContext()
    action = await engine.attempt(failed=..., page=..., original=..., ctx=ctx)

Adding a strategy: drop a module under `recovery/strategies/`, add it to
`default_strategies()` in that package's `__init__.py`, and add a unit test.
The engine never changes.
"""

from .engine import RecoveryEngine
from .protocol import (
    RecoveryContext,
    RecoveryDecision,
    SelectorPromptStrategy,
    SelectorResponseParser,
    Strategy,
)
from .strategies import default_strategies


def default_engine() -> RecoveryEngine:
    """Curated engine, sorted by ascending `cost_tier`.

    Order: wait_and_retry → scroll_into_view → dismiss_modal → frame_switch
    → llm_reselect.
    """
    return RecoveryEngine(default_strategies())


__all__ = [
    "RecoveryContext",
    "RecoveryDecision",
    "RecoveryEngine",
    "SelectorPromptStrategy",
    "SelectorResponseParser",
    "Strategy",
    "default_engine",
    "default_strategies",
]
