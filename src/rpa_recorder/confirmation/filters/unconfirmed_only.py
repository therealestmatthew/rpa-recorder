"""M11 filter: skip actions the user has already accepted/relabeled."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rpa_recorder.models import RecordedAction, Recording


class UnconfirmedOnlyFilter:
    """Selects actions where `user_confirmed is False`."""

    name = "unconfirmed_only"

    def select(self, recording: Recording, *, threshold: float) -> list[RecordedAction]:
        del threshold
        return [a for a in recording.actions if not a.user_confirmed]


__all__ = ["UnconfirmedOnlyFilter"]
