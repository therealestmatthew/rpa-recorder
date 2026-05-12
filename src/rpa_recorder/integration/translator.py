"""`SeleniumEventTranslator` — `SeleniumEvent` → `RecordedAction`.

Stateless: the translator does not own sequence numbers or recording IDs.
The caller (`IngestSession`) assigns those at ingestion time.

The translator picks the most robust available locator strategies from
`SeleniumLocators` and packs as many as possible into `ElementSelector`
so replay has multiple fallbacks. Per-event-type payload construction
honors `is_sensitive` auto-detection from `target.input_type == "password"`.
"""

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal, cast
from uuid import uuid4

from rpa_recorder.models import (
    ActionType,
    ClickPayload,
    ElementContext,
    ElementSelector,
    InputPayload,
    NavigatePayload,
    RecordedAction,
    SelectPayload,
)

if TYPE_CHECKING:
    from rpa_recorder.integration.events import (
        SeleniumEvent,
        SeleniumLocators,
        SeleniumTarget,
    )
    from rpa_recorder.models.actions import ActionPayload


_PASSWORD_INPUT_TYPES: frozenset[str] = frozenset({"password"})

_VALID_BUTTONS: frozenset[str] = frozenset({"left", "right", "middle"})

_VALID_WAIT_UNTIL: frozenset[str] = frozenset({"load", "domcontentloaded", "networkidle"})


def _css_escape_attr_value(value: str) -> str:
    """Escape a value for safe inclusion inside `[attr="..."]`."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _build_selector(locators: SeleniumLocators | None) -> ElementSelector | None:
    """Pack every available locator strategy into one `ElementSelector`.

    Replay evaluates the selector fields in robustness order
    (role+name > test_id > css > xpath > text), so we populate as many as
    the host provided. Returning `None` when no field is set keeps the
    JSON output of `RecordedAction.model_dump()` slim.
    """
    if locators is None:
        return None

    css = locators.css
    if css is None and locators.id:
        css = f"#{locators.id}"
    elif css is None and locators.name:
        css = f'[name="{_css_escape_attr_value(locators.name)}"]'
    elif css is None and locators.class_name:
        css = f".{locators.class_name}"
    elif css is None and locators.tag_name:
        css = locators.tag_name

    text_content = locators.link_text or locators.partial_link_text

    selector = ElementSelector(
        role=locators.aria_role,
        accessible_name=locators.aria_label,
        test_id=locators.test_id,
        text_content=text_content,
        css=css,
        xpath=locators.xpath,
        nth=locators.nth,
    )

    populated = (
        selector.role
        or selector.accessible_name
        or selector.test_id
        or selector.text_content
        or selector.css
        or selector.xpath
        or selector.nth is not None
    )
    return selector if populated else None


def _build_context(target: SeleniumTarget | None) -> ElementContext | None:
    if target is None:
        return None
    # Mirror `input_type` into `attributes["type"]` if the host did not already
    # set it there. Several heuristic rules (login, form_fill) read `type` from
    # attributes, so this keeps two equivalent host-side conventions equivalent
    # downstream.
    attributes = dict(target.attributes)
    if target.input_type and "type" not in attributes:
        attributes["type"] = target.input_type
    return ElementContext(
        tag=target.tag,
        attributes=attributes,
        visible_text=target.visible_text,
        bounding_box=dict(target.bounding_box) if target.bounding_box else None,
        is_visible=target.is_visible,
        is_enabled=target.is_enabled,
        parent_form_id=target.parent_form_id,
        nearby_labels=list(target.nearby_labels),
    )


def _is_sensitive(target: SeleniumTarget | None, payload: dict[str, object]) -> bool:
    if "is_sensitive" in payload:
        return bool(payload["is_sensitive"])
    if target is not None and target.input_type:
        return target.input_type.lower() in _PASSWORD_INPUT_TYPES
    return False


def _click_payload(payload: dict[str, object]) -> ClickPayload:
    button_raw = str(payload.get("button", "left"))
    button = cast(
        "Literal['left', 'right', 'middle']",
        button_raw if button_raw in _VALID_BUTTONS else "left",
    )
    modifiers = payload.get("modifiers", [])
    if not isinstance(modifiers, list):
        modifiers = []
    return ClickPayload(button=button, modifiers=[str(m) for m in modifiers])


def _input_payload(target: SeleniumTarget | None, payload: dict[str, object]) -> InputPayload:
    return InputPayload(
        value=str(payload.get("value", "")),
        is_sensitive=_is_sensitive(target, payload),
        clear_first=bool(payload.get("clear_first", True)),
    )


def _navigate_payload(payload: dict[str, object], event_url: str) -> NavigatePayload:
    url = str(payload.get("url") or event_url)
    wait_until_raw = str(payload.get("wait_until", "load"))
    wait_until = cast(
        "Literal['load', 'domcontentloaded', 'networkidle']",
        wait_until_raw if wait_until_raw in _VALID_WAIT_UNTIL else "load",
    )
    return NavigatePayload(url=url, wait_until=wait_until)


def _select_payload(payload: dict[str, object]) -> SelectPayload:
    values = payload.get("values", [])
    if not isinstance(values, list):
        values = [values] if values else []
    return SelectPayload(values=[str(v) for v in values])


_DIRECT_EVENT_TYPE_MAP: dict[str, ActionType] = {
    "click": ActionType.CLICK,
    "input": ActionType.INPUT,
    "navigate": ActionType.NAVIGATE,
    "key_press": ActionType.KEY_PRESS,
    "submit": ActionType.CLICK,
}


def _resolve_change_action_type(target: SeleniumTarget | None) -> ActionType:
    """`change` fans out by target tag/type.

    <select> → SELECT, checkbox/radio → CLICK (matches the Playwright recorder's
    existing behavior in `page_scripts/recorder/inject.js`), everything else
    → INPUT.
    """
    tag = target.tag.lower() if target else ""
    input_type = target.input_type.lower() if target and target.input_type else ""
    if tag == "select":
        return ActionType.SELECT
    if tag == "input" and input_type in {"checkbox", "radio"}:
        return ActionType.CLICK
    return ActionType.INPUT


def _resolve_action_type(event: SeleniumEvent) -> ActionType:
    """Map `event_type` (+ target tag for `change`) → `ActionType`."""
    direct = _DIRECT_EVENT_TYPE_MAP.get(event.event_type)
    if direct is not None:
        return direct
    return _resolve_change_action_type(event.target)


def _build_payload(action_type: ActionType, event: SeleniumEvent) -> ActionPayload:
    if action_type == ActionType.CLICK:
        return _click_payload(event.payload)
    if action_type == ActionType.INPUT:
        return _input_payload(event.target, event.payload)
    if action_type == ActionType.SELECT:
        return _select_payload(event.payload)
    if action_type == ActionType.NAVIGATE:
        return _navigate_payload(event.payload, event.url)
    if action_type == ActionType.KEY_PRESS:
        return dict(event.payload)
    return dict(event.payload)


class SeleniumEventTranslator:
    """Stateless translator: `SeleniumEvent` → `RecordedAction`.

    Sequence numbers and recording IDs are NOT assigned here — the caller
    (typically `IngestSession`) owns that. Keeping the translator stateless
    makes it trivially unit-testable and reusable across sessions.
    """

    def translate(self, event: SeleniumEvent, *, sequence: int) -> RecordedAction:
        """Build a `RecordedAction` from one `SeleniumEvent`."""
        action_type = _resolve_action_type(event)
        payload = _build_payload(action_type, event)
        timestamp = datetime.fromtimestamp(event.timestamp_ms / 1000.0, tz=UTC)
        return RecordedAction(
            id=uuid4(),
            sequence=sequence,
            timestamp=timestamp,
            action_type=action_type,
            payload=payload,
            selector=_build_selector(event.locators),
            element_context=_build_context(event.target),
            url=event.url,
            page_title=event.page_title,
            frame_url=event.frame_url,
            viewport=dict(event.viewport) if event.viewport else None,
        )


__all__ = ["SeleniumEventTranslator"]
