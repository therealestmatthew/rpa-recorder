"""Library-mode integration surface for external recorders (e.g. Selenium).

Bridges host-side event capture to `rpa_recorder`'s pure-Python pipeline:
host emits `SeleniumEvent`s → `SeleniumEventTranslator` maps them to
`RecordedAction` → `IngestSession` (or `SyncIngestSession`) lands them in
the bronze tier and runs the heuristic classifier.

No `selenium` import lives here. The translator and session take plain dicts
or Pydantic models, so the package stays driver-agnostic. Hosts bring their
own Selenium driver and JS injection; this module starts where their captured
event dicts arrive in Python.
"""

from rpa_recorder.integration.events import (
    EventType,
    SeleniumEvent,
    SeleniumLocators,
    SeleniumTarget,
)
from rpa_recorder.integration.session import IngestSession, SyncIngestSession
from rpa_recorder.integration.translator import SeleniumEventTranslator

__all__ = [
    "EventType",
    "IngestSession",
    "SeleniumEvent",
    "SeleniumEventTranslator",
    "SeleniumLocators",
    "SeleniumTarget",
    "SyncIngestSession",
]
