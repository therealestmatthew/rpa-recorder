"""Default strategy roster for the recovery engine.

Adding a new strategy: drop a module in this package, append the constructor
to `default_strategies()`, and write a unit test. The engine never changes.
"""

from typing import TYPE_CHECKING

from .dismiss_modal import DismissModalStrategy
from .frame_switch import FrameSwitchStrategy
from .llm_reselect import LLMReselectStrategy
from .scroll_into_view import ScrollIntoViewStrategy
from .wait_and_retry import WaitAndRetryStrategy

if TYPE_CHECKING:
    from rpa_recorder.recovery.protocol import Strategy


def default_strategies() -> list[Strategy]:
    """Curated default roster, sorted by ascending `cost_tier`."""
    return [
        WaitAndRetryStrategy(),
        ScrollIntoViewStrategy(),
        DismissModalStrategy(),
        FrameSwitchStrategy(),
        LLMReselectStrategy(),
    ]


__all__ = [
    "DismissModalStrategy",
    "FrameSwitchStrategy",
    "LLMReselectStrategy",
    "ScrollIntoViewStrategy",
    "WaitAndRetryStrategy",
    "default_strategies",
]
