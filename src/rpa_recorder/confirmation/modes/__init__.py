"""Review-mode registry for the M11 confirmation pipeline."""

from typing import TYPE_CHECKING, Any

from rpa_recorder.config import Config
from rpa_recorder.confirmation.modes.diff_baseline import DiffBaselineMode
from rpa_recorder.confirmation.modes.overview import OverviewMode
from rpa_recorder.confirmation.modes.per_action import PerActionMode
from rpa_recorder.confirmation.modes.per_intent_batch import PerIntentBatchMode

if TYPE_CHECKING:
    from collections.abc import Callable

    from rpa_recorder.confirmation.protocol import ReviewMode

_MODES: dict[str, Callable[..., ReviewMode]] = {
    "per_action": PerActionMode,
    "per_intent_batch": PerIntentBatchMode,
    "overview": OverviewMode,
    "diff_baseline": DiffBaselineMode,
}


def default_modes() -> dict[str, Callable[..., ReviewMode]]:
    """Snapshot of the registry; callers may add or override."""
    return dict(_MODES)


def default_mode(name: str | None = None, **kwargs: Any) -> ReviewMode:
    """Construct a mode from the registry. Defaults to Config setting."""
    resolved = name or Config().confirmation_default_mode
    cls = _MODES[resolved]
    return cls(**kwargs)


__all__ = [
    "DiffBaselineMode",
    "OverviewMode",
    "PerActionMode",
    "PerIntentBatchMode",
    "default_mode",
    "default_modes",
]
