"""Default M11 filter: select actions whose classifier confidence is too low."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rpa_recorder.models import RecordedAction, Recording


class BelowThresholdFilter:
    """Selects actions where `classification_confidence < threshold`."""

    name = "below_threshold"

    def select(self, recording: Recording, *, threshold: float) -> list[RecordedAction]:
        return [a for a in recording.actions if a.classification_confidence < threshold]


__all__ = ["BelowThresholdFilter"]
