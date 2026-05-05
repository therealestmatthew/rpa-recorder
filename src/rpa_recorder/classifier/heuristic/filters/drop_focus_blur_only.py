"""Drop INPUT actions with empty value and no follow-up typing on the same selector."""

from typing import TYPE_CHECKING

from rpa_recorder.models import ActionType, InputPayload, RecordedAction

if TYPE_CHECKING:
    from ..protocol import RuleContext

_FOLLOWUP_WINDOW_MS: float = 2000.0


class DropFocusBlurOnly:
    """Drops focus/blur events that registered as INPUT but never received text.

    A real type-and-leave produces an INPUT with non-empty value. A focus-only
    interaction produces an INPUT with `value=""`; if no later INPUT on the same
    selector arrives within 2000 ms, the user only focused-then-left.
    """

    name: str = "drop_focus_blur_only"

    def apply(self, action: RecordedAction, ctx: RuleContext) -> bool:
        if action.action_type is not ActionType.INPUT:
            return True
        if not isinstance(action.payload, InputPayload):
            return True
        if action.payload.value != "":
            return True
        for cand in ctx.actions[ctx.index + 1 :]:
            if cand.action_type is not ActionType.INPUT:
                continue
            if cand.selector != action.selector:
                continue
            dt_ms = (cand.timestamp - action.timestamp).total_seconds() * 1000.0
            if dt_ms > _FOLLOWUP_WINDOW_MS:
                break
            return True
        return False
