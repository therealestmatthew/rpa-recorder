"""Strip surrounding whitespace from non-sensitive INPUT values."""

from typing import TYPE_CHECKING

from rpa_recorder.models import ActionType, InputPayload, RecordedAction

if TYPE_CHECKING:
    from ..protocol import RuleContext


class TrimInputValue:
    """Trims `payload.value` for INPUT actions, except when `is_sensitive=True`.

    Passwords often have intentional leading/trailing characters that we must
    not silently strip, hence the sensitivity check.
    """

    name: str = "trim_input_value"

    def apply(self, action: RecordedAction, ctx: RuleContext) -> RecordedAction:  # noqa: ARG002
        if action.action_type is not ActionType.INPUT:
            return action
        if not isinstance(action.payload, InputPayload):
            return action
        if action.payload.is_sensitive:
            return action
        trimmed = action.payload.value.strip()
        if trimmed == action.payload.value:
            return action
        new_payload = action.payload.model_copy(update={"value": trimmed})
        return action.model_copy(update={"payload": new_payload})
