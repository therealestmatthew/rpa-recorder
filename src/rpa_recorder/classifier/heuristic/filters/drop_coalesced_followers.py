"""Drop INPUT actions whose sequence was marked as a coalesce follower.

Paired with `coalesce_input_bursts` (normalizer): when a burst of rapid
keystrokes on the same selector is collapsed to a single merged action, the
followers' `sequence` numbers are added to `ctx.scratch["coalesced_indexes"]`.
This filter consumes that set during the engine's post-normalize filter pass.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rpa_recorder.models import RecordedAction

    from ..protocol import RuleContext


class DropCoalescedFollowers:
    """Removes INPUT actions whose sequence was marked by the coalesce normalizer."""

    name: str = "drop_coalesced_followers"

    def apply(self, action: RecordedAction, ctx: RuleContext) -> bool:
        marked = ctx.scratch.get("coalesced_indexes")
        if not isinstance(marked, set):
            return True
        return action.sequence not in marked
