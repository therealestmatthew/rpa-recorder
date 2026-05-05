"""Filter pipeline registry. Add a rule by importing it and appending to `default_filters()`."""

from typing import TYPE_CHECKING

from .drop_coalesced_followers import DropCoalescedFollowers
from .drop_disabled_target import DropDisabledTarget
from .drop_duplicate_navigate import DropDuplicateNavigate
from .drop_focus_blur_only import DropFocusBlurOnly

if TYPE_CHECKING:
    from ..protocol import FilterRule


def default_filters() -> list[FilterRule]:
    """Project's curated default filter rule set."""
    return [
        DropFocusBlurOnly(),
        DropDuplicateNavigate(),
        DropDisabledTarget(),
        DropCoalescedFollowers(),
    ]


__all__ = [
    "DropCoalescedFollowers",
    "DropDisabledTarget",
    "DropDuplicateNavigate",
    "DropFocusBlurOnly",
    "default_filters",
]
