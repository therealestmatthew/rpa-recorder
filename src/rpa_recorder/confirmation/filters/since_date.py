"""M11 filter: select actions newer than a cutoff (recording's `timestamp`)."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

    from rpa_recorder.models import RecordedAction, Recording


class SinceDateFilter:
    """Selects actions whose `timestamp >= cutoff`."""

    name = "since_date"

    def __init__(self, cutoff: datetime) -> None:
        self._cutoff = cutoff

    def select(self, recording: Recording, *, threshold: float) -> list[RecordedAction]:
        del threshold
        return [a for a in recording.actions if a.timestamp >= self._cutoff]


__all__ = ["SinceDateFilter"]
