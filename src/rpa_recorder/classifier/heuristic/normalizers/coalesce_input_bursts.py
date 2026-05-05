"""Collapse rapid-keystroke INPUT bursts on the same selector into one merged action.

The leader keeps the *last* value typed; followers' sequence numbers are
recorded in `ctx.scratch["coalesced_indexes"]` so the paired
`drop_coalesced_followers` filter can drop them in the post-normalize pass.

A "burst" is a sequence of consecutive INPUT actions on the same selector
where each successive action arrives within `_BURST_GAP_MS` of the previous
one (sliding window — supports keystroke-style typing).
"""

from typing import TYPE_CHECKING

from rpa_recorder.models import ActionType, InputPayload, RecordedAction

if TYPE_CHECKING:
    from ..protocol import RuleContext

_BURST_GAP_MS: float = 200.0


class CoalesceInputBursts:
    """Merge rapid keystrokes on the same selector into a single carrier action."""

    name: str = "coalesce_input_bursts"

    def apply(self, action: RecordedAction, ctx: RuleContext) -> RecordedAction:
        if action.action_type is not ActionType.INPUT:
            return action
        if not isinstance(action.payload, InputPayload):
            return action
        coalesced = ctx.scratch.setdefault("coalesced_indexes", set())
        if action.sequence in coalesced:
            return action

        follower_sequences: list[int] = []
        last_value: str = action.payload.value
        prev_ts = action.timestamp
        i = ctx.index + 1
        while i < len(ctx.actions):
            cand = ctx.actions[i]
            if cand.action_type is not ActionType.INPUT:
                break
            if cand.selector != action.selector:
                break
            if not isinstance(cand.payload, InputPayload):
                break
            dt_ms = (cand.timestamp - prev_ts).total_seconds() * 1000.0
            if dt_ms > _BURST_GAP_MS:
                break
            follower_sequences.append(cand.sequence)
            last_value = cand.payload.value
            prev_ts = cand.timestamp
            i += 1

        if not follower_sequences:
            return action

        coalesced.update(follower_sequences)
        if last_value == action.payload.value:
            return action
        new_payload = action.payload.model_copy(update={"value": last_value})
        return action.model_copy(update={"payload": new_payload})
