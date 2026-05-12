"""Input event shape for `rpa_recorder.integration`.

This is the contract an external host (e.g. a Selenium-based recorder) emits.
The translator in `translator.py` maps these into `RecordedAction` instances —
the canonical model the rest of the package consumes.

The shape is intentionally permissive: hosts populate whatever fields they have
captured. Required fields (`event_type`, `timestamp_ms`, `url`) are the bare
minimum needed to land a row in bronze; everything else improves classifier
quality and replay robustness.

No `selenium` import lives here — the model takes plain dicts/strings, so
`rpa_recorder` stays driver-agnostic.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field

EventType = Literal[
    "click",
    "input",
    "change",
    "navigate",
    "key_press",
    "submit",
]


class SeleniumLocators(BaseModel):
    """Element-targeting hints captured by the host.

    Mirrors Selenium's `By.*` strategies plus accessibility attributes the host
    can derive via in-page JS (e.g. `element.getAttribute('aria-label')`).
    The translator picks the most robust available locator when building
    `ElementSelector`.
    """

    id: str | None = None
    name: str | None = None
    css: str | None = None
    xpath: str | None = None
    link_text: str | None = None
    partial_link_text: str | None = None
    tag_name: str | None = None
    class_name: str | None = None
    aria_label: str | None = None
    aria_role: str | None = None
    test_id: str | None = None
    nth: int | None = None


class SeleniumTarget(BaseModel):
    """Snapshot of the targeted element at event time."""

    tag: str
    attributes: dict[str, str] = Field(default_factory=dict)
    visible_text: str | None = None
    bounding_box: dict[str, float] | None = None
    is_visible: bool = True
    is_enabled: bool = True
    parent_form_id: str | None = None
    nearby_labels: list[str] = Field(default_factory=list)
    input_type: str | None = None


class SeleniumEvent(BaseModel):
    """One captured event from the host's recorder.

    `payload` carries event-type-specific fields the translator pulls from:
        - click:      `{button: "left"|"right"|"middle", modifiers: list[str]}`
        - input:      `{value: str, is_sensitive: bool, clear_first: bool}`
        - change:     `{values: list[str]}`  (for <select>; checkboxes use `click` flow)
        - navigate:   `{url: str, wait_until: "load"|"domcontentloaded"|"networkidle"}`
        - key_press:  `{key: str}`           (only "Enter" is currently surfaced)
        - submit:     `{}`                   (treated as click on the submit element)
    Missing fields fall back to sensible defaults.
    """

    event_type: EventType
    timestamp_ms: int
    url: str
    page_title: str | None = None
    frame_url: str | None = None
    viewport: dict[str, int] | None = None
    target: SeleniumTarget | None = None
    locators: SeleniumLocators | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "EventType",
    "SeleniumEvent",
    "SeleniumLocators",
    "SeleniumTarget",
]
