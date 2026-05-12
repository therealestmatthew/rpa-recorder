"""rpa-recorder: semantic browser RPA with record, classify, replay, and recover.

Public library API. Hosts that import `rpa_recorder` should reach for these
re-exports rather than internal module paths so internal layout can evolve
without breaking consumers.

For external recorders (e.g. Selenium), see `rpa_recorder.integration` —
`SeleniumEvent`, `SeleniumEventTranslator`, `IngestSession`, and
`SyncIngestSession` are also re-exported here for ergonomic top-level access.
"""

from rpa_recorder.classifier.heuristic import (
    Classification,
    HeuristicEngine,
    classify,
    default_pipeline,
)
from rpa_recorder.config import Config
from rpa_recorder.integration import (
    EventType,
    IngestSession,
    SeleniumEvent,
    SeleniumEventTranslator,
    SeleniumLocators,
    SeleniumTarget,
    SyncIngestSession,
)
from rpa_recorder.medallion.bronze import BronzeWriter
from rpa_recorder.medallion.bronze_store import BronzeStore, LocalFilesystemStore
from rpa_recorder.models import (
    REDACTED_VALUE,
    ActionPayload,
    ActionType,
    ClickPayload,
    ElementContext,
    ElementSelector,
    InputPayload,
    NavigatePayload,
    NetworkEvent,
    ParameterDef,
    RecordedAction,
    Recording,
    SelectPayload,
    SemanticIntent,
)

__version__ = "0.2.0"

__all__ = [
    "REDACTED_VALUE",
    "ActionPayload",
    "ActionType",
    "BronzeStore",
    "BronzeWriter",
    "Classification",
    "ClickPayload",
    "Config",
    "ElementContext",
    "ElementSelector",
    "EventType",
    "HeuristicEngine",
    "IngestSession",
    "InputPayload",
    "LocalFilesystemStore",
    "NavigatePayload",
    "NetworkEvent",
    "ParameterDef",
    "RecordedAction",
    "Recording",
    "SelectPayload",
    "SeleniumEvent",
    "SeleniumEventTranslator",
    "SeleniumLocators",
    "SeleniumTarget",
    "SemanticIntent",
    "SyncIngestSession",
    "__version__",
    "classify",
    "default_pipeline",
]
