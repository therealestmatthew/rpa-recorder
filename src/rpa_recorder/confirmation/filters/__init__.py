"""Filter registry for the M11 confirmation pipeline.

Each filter is a single class in its own module. Add a new filter by
creating the module and appending one entry to `_FILTERS` below — no
edits to the runner or other filters.
"""

from typing import TYPE_CHECKING, Any

from rpa_recorder.config import Config
from rpa_recorder.confirmation.filters.below_threshold import BelowThresholdFilter
from rpa_recorder.confirmation.filters.by_intent import ByIntentFilter
from rpa_recorder.confirmation.filters.failed_on_replay import FailedOnReplayFilter
from rpa_recorder.confirmation.filters.since_date import SinceDateFilter
from rpa_recorder.confirmation.filters.unconfirmed_only import UnconfirmedOnlyFilter

if TYPE_CHECKING:
    from collections.abc import Callable

    from rpa_recorder.confirmation.protocol import Filter

_FILTERS: dict[str, Callable[..., Filter]] = {
    "below_threshold": BelowThresholdFilter,
    "by_intent": ByIntentFilter,
    "failed_on_replay": FailedOnReplayFilter,
    "unconfirmed_only": UnconfirmedOnlyFilter,
    "since_date": SinceDateFilter,
}


def default_filters() -> dict[str, Callable[..., Filter]]:
    """Snapshot of the registry; callers may add or override."""
    return dict(_FILTERS)


def default_filter(name: str | None = None, **kwargs: Any) -> Filter:
    """Construct a filter from the registry. Defaults to Config setting."""
    resolved = name or Config().confirmation_default_filter
    cls = _FILTERS[resolved]
    return cls(**kwargs)


__all__ = [
    "BelowThresholdFilter",
    "ByIntentFilter",
    "FailedOnReplayFilter",
    "SinceDateFilter",
    "UnconfirmedOnlyFilter",
    "default_filter",
    "default_filters",
]
