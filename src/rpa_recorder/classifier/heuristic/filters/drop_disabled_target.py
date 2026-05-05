"""Drop actions whose element_context reports `is_enabled=False`."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rpa_recorder.models import RecordedAction

    from ..protocol import RuleContext


class DropDisabledTarget:
    """Defensive: flaky pages occasionally fire events on disabled elements.

    The recorder respects the page's `is_enabled` snapshot at capture time;
    if it says False, the action couldn't have meaningfully run, so we drop it.
    """

    name: str = "drop_disabled_target"

    def apply(self, action: RecordedAction, ctx: RuleContext) -> bool:  # noqa: ARG002
        if action.element_context is None:
            return True
        return action.element_context.is_enabled
