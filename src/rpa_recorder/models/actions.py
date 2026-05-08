"""Action enums, selectors, payloads, and `RecordedAction`."""

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import (
    BaseModel,
    Field,
    SerializationInfo,
    SerializerFunctionWrapHandler,
    model_serializer,
)

REDACTED_VALUE = "***REDACTED***"


class ActionType(StrEnum):
    """Low-level event taxonomy: how an action manifested in the browser."""

    CLICK = "click"
    INPUT = "input"
    NAVIGATE = "navigate"
    SELECT = "select"
    HOVER = "hover"
    KEY_PRESS = "key_press"
    SCROLL = "scroll"
    WAIT = "wait"
    ASSERT = "assert"
    UPLOAD = "upload"


class SemanticIntent(StrEnum):
    """Classifier output — what an action means, not how it was done."""

    LOGIN = "login"
    SEARCH = "search"
    FORM_FILL = "form_fill"
    FORM_SUBMIT = "form_submit"
    NAVIGATION = "navigation"
    DATA_EXTRACTION = "data_extraction"
    CONFIRMATION = "confirmation"
    DISMISS_MODAL = "dismiss_modal"
    SELECTION = "selection"
    UNKNOWN = "unknown"


class ElementSelector(BaseModel):
    """Multiple targeting strategies, ordered by robustness.

    Replay tries them in order until one resolves uniquely.
    """

    role: str | None = None
    accessible_name: str | None = None
    test_id: str | None = None
    text_content: str | None = None
    css: str | None = None
    xpath: str | None = None
    nth: int | None = None
    frame_url: str | None = None


class ElementContext(BaseModel):
    """Snapshot of element state at record time."""

    tag: str
    attributes: dict[str, str] = Field(default_factory=dict)
    visible_text: str | None = None
    bounding_box: dict[str, float] | None = None
    is_visible: bool = True
    is_enabled: bool = True
    parent_form_id: str | None = None
    nearby_labels: list[str] = Field(default_factory=list)


class ClickPayload(BaseModel):
    """Click-specific event data."""

    button: Literal["left", "right", "middle"] = "left"
    modifiers: list[str] = Field(default_factory=list)


class InputPayload(BaseModel):
    """Text/value input event data; `is_sensitive` triggers redaction on output."""

    value: str
    is_sensitive: bool = False
    clear_first: bool = True

    @model_serializer(mode="wrap")
    def _redact_if_secret(
        self,
        handler: SerializerFunctionWrapHandler,
        info: SerializationInfo,
    ) -> dict[str, Any]:
        data: dict[str, Any] = handler(self)
        ctx = info.context
        if isinstance(ctx, dict) and ctx.get("redact_secrets") and self.is_sensitive:
            data["value"] = REDACTED_VALUE
        return data


class NavigatePayload(BaseModel):
    """Navigation event data."""

    url: str
    wait_until: Literal["load", "domcontentloaded", "networkidle"] = "load"


class SelectPayload(BaseModel):
    """Dropdown/select event data."""

    values: list[str]


ActionPayload = ClickPayload | InputPayload | NavigatePayload | SelectPayload | dict[str, Any]


class RecordedAction(BaseModel):
    """A single user action captured by the recorder."""

    id: UUID = Field(default_factory=uuid4)
    sequence: int
    timestamp: datetime
    action_type: ActionType
    payload: ActionPayload

    selector: ElementSelector | None = None
    element_context: ElementContext | None = None

    url: str
    page_title: str | None = None
    frame_url: str | None = None
    viewport: dict[str, int] | None = None

    semantic_intent: SemanticIntent = SemanticIntent.UNKNOWN
    classification_confidence: float = 0.0
    classification_reasoning: str | None = None
    user_confirmed: bool = False
    user_label: str | None = None

    is_parameterized: bool = False
    parameter_name: str | None = None
