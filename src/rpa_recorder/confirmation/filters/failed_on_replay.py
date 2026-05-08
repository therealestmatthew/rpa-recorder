"""M11 filter: select only actions that failed during recent replays.

Construction takes the precomputed set of failed action IDs so the filter
itself stays pure-data (no DB session). The CLI command resolves the set
once before building the runner, by joining `ExecutionAttemptRow` against
`ActionExecutionRow` for the recording's recent runs.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable
    from uuid import UUID

    from rpa_recorder.models import RecordedAction, Recording


class FailedOnReplayFilter:
    """Selects actions whose `id` is in the supplied failed-action set."""

    name = "failed_on_replay"

    def __init__(self, failed_action_ids: Iterable[UUID]) -> None:
        self._failed: frozenset[UUID] = frozenset(failed_action_ids)

    def select(self, recording: Recording, *, threshold: float) -> list[RecordedAction]:
        del threshold
        return [a for a in recording.actions if a.id in self._failed]


__all__ = ["FailedOnReplayFilter"]
