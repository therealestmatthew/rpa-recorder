"""M11 filter: select actions whose classifier guessed a specific intent.

Used by `rpa confirm --filter by_intent --intent search` to bulk-review every
SEARCH action in a recording without touching the rest.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rpa_recorder.models import RecordedAction, Recording, SemanticIntent


class ByIntentFilter:
    """Selects actions where `semantic_intent == intent`."""

    name = "by_intent"

    def __init__(self, intent: SemanticIntent) -> None:
        self._intent = intent

    def select(self, recording: Recording, *, threshold: float) -> list[RecordedAction]:
        del threshold
        return [a for a in recording.actions if a.semantic_intent == self._intent]


__all__ = ["ByIntentFilter"]
