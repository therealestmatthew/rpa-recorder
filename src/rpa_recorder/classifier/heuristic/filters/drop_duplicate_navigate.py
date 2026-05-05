"""Drop NAVIGATE actions that target the same URL as the immediately preceding action."""

from typing import TYPE_CHECKING

from rpa_recorder.models import ActionType, NavigatePayload, RecordedAction

if TYPE_CHECKING:
    from ..protocol import RuleContext


def _navigate_url(action: RecordedAction) -> str | None:
    if action.action_type is not ActionType.NAVIGATE:
        return None
    if isinstance(action.payload, NavigatePayload):
        return action.payload.url
    if isinstance(action.payload, dict):
        url = action.payload.get("url")
        return url if isinstance(url, str) else None
    return None


class DropDuplicateNavigate:
    """Drops idempotent reloads and hash-only re-navigations.

    Compares the destination URL of consecutive NAVIGATE actions; if the
    previous action was also a NAVIGATE to the same URL, this one is dropped.
    """

    name: str = "drop_duplicate_navigate"

    def apply(self, action: RecordedAction, ctx: RuleContext) -> bool:
        current = _navigate_url(action)
        if current is None:
            return True
        if ctx.index == 0:
            return True
        previous = _navigate_url(ctx.actions[ctx.index - 1])
        if previous is None:
            return True
        return previous != current
