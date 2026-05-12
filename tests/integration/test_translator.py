"""Unit tests for `SeleniumEventTranslator` (pure mapping; no I/O).

Each test builds a `SeleniumEvent` directly, runs translation, and asserts
the resulting `RecordedAction` shape. Sequence numbers are passed in by the
caller (the session, in production), so we just hand 0 here.
"""

from rpa_recorder.integration.events import (
    SeleniumEvent,
    SeleniumLocators,
    SeleniumTarget,
)
from rpa_recorder.integration.translator import SeleniumEventTranslator
from rpa_recorder.models import (
    ActionType,
    ClickPayload,
    InputPayload,
    NavigatePayload,
    RecordedAction,
    SelectPayload,
)


def _translate(event: SeleniumEvent) -> RecordedAction:
    return SeleniumEventTranslator().translate(event, sequence=0)


class TestEventTypeMapping:
    def test_click_event_maps_to_click_action(self) -> None:
        action = _translate(
            SeleniumEvent(
                event_type="click",
                timestamp_ms=1_000,
                url="https://example.com/",
                payload={"button": "left"},
            ),
        )
        assert action.action_type == ActionType.CLICK
        assert isinstance(action.payload, ClickPayload)
        assert action.payload.button == "left"

    def test_input_event_maps_to_input_action(self) -> None:
        action = _translate(
            SeleniumEvent(
                event_type="input",
                timestamp_ms=1_000,
                url="https://example.com/",
                payload={"value": "alice"},
            ),
        )
        assert action.action_type == ActionType.INPUT
        assert isinstance(action.payload, InputPayload)
        assert action.payload.value == "alice"
        assert action.payload.is_sensitive is False

    def test_change_on_select_maps_to_select_action(self) -> None:
        action = _translate(
            SeleniumEvent(
                event_type="change",
                timestamp_ms=1_000,
                url="https://example.com/",
                target=SeleniumTarget(tag="select"),
                payload={"values": ["NY", "CA"]},
            ),
        )
        assert action.action_type == ActionType.SELECT
        assert isinstance(action.payload, SelectPayload)
        assert action.payload.values == ["NY", "CA"]

    def test_change_on_checkbox_maps_to_click(self) -> None:
        action = _translate(
            SeleniumEvent(
                event_type="change",
                timestamp_ms=1_000,
                url="https://example.com/",
                target=SeleniumTarget(tag="input", input_type="checkbox"),
            ),
        )
        assert action.action_type == ActionType.CLICK

    def test_change_on_radio_maps_to_click(self) -> None:
        action = _translate(
            SeleniumEvent(
                event_type="change",
                timestamp_ms=1_000,
                url="https://example.com/",
                target=SeleniumTarget(tag="input", input_type="radio"),
            ),
        )
        assert action.action_type == ActionType.CLICK

    def test_navigate_uses_payload_url(self) -> None:
        action = _translate(
            SeleniumEvent(
                event_type="navigate",
                timestamp_ms=1_000,
                url="https://example.com/old",
                payload={"url": "https://example.com/new"},
            ),
        )
        assert action.action_type == ActionType.NAVIGATE
        assert isinstance(action.payload, NavigatePayload)
        assert action.payload.url == "https://example.com/new"

    def test_navigate_falls_back_to_event_url(self) -> None:
        action = _translate(
            SeleniumEvent(
                event_type="navigate",
                timestamp_ms=1_000,
                url="https://example.com/page",
            ),
        )
        assert isinstance(action.payload, NavigatePayload)
        assert action.payload.url == "https://example.com/page"

    def test_submit_maps_to_click(self) -> None:
        action = _translate(
            SeleniumEvent(
                event_type="submit",
                timestamp_ms=1_000,
                url="https://example.com/",
            ),
        )
        assert action.action_type == ActionType.CLICK

    def test_key_press_maps_to_key_press(self) -> None:
        action = _translate(
            SeleniumEvent(
                event_type="key_press",
                timestamp_ms=1_000,
                url="https://example.com/",
                payload={"key": "Enter"},
            ),
        )
        assert action.action_type == ActionType.KEY_PRESS


class TestSensitiveDetection:
    def test_password_input_type_marks_sensitive(self) -> None:
        action = _translate(
            SeleniumEvent(
                event_type="input",
                timestamp_ms=1_000,
                url="https://example.com/",
                target=SeleniumTarget(tag="input", input_type="password"),
                payload={"value": "secret"},
            ),
        )
        assert isinstance(action.payload, InputPayload)
        assert action.payload.is_sensitive is True

    def test_explicit_payload_flag_overrides_type(self) -> None:
        action = _translate(
            SeleniumEvent(
                event_type="input",
                timestamp_ms=1_000,
                url="https://example.com/",
                target=SeleniumTarget(tag="input", input_type="text"),
                payload={"value": "card", "is_sensitive": True},
            ),
        )
        assert isinstance(action.payload, InputPayload)
        assert action.payload.is_sensitive is True

    def test_text_input_is_not_sensitive_by_default(self) -> None:
        action = _translate(
            SeleniumEvent(
                event_type="input",
                timestamp_ms=1_000,
                url="https://example.com/",
                target=SeleniumTarget(tag="input", input_type="text"),
                payload={"value": "alice"},
            ),
        )
        assert isinstance(action.payload, InputPayload)
        assert action.payload.is_sensitive is False


class TestLocatorMapping:
    def test_id_becomes_css_id_selector(self) -> None:
        action = _translate(
            SeleniumEvent(
                event_type="click",
                timestamp_ms=1_000,
                url="https://example.com/",
                locators=SeleniumLocators(id="submit-btn"),
            ),
        )
        assert action.selector is not None
        assert action.selector.css == "#submit-btn"

    def test_explicit_css_takes_precedence_over_id(self) -> None:
        action = _translate(
            SeleniumEvent(
                event_type="click",
                timestamp_ms=1_000,
                url="https://example.com/",
                locators=SeleniumLocators(id="submit-btn", css=".primary"),
            ),
        )
        assert action.selector is not None
        assert action.selector.css == ".primary"

    def test_name_becomes_attr_css_when_no_id(self) -> None:
        action = _translate(
            SeleniumEvent(
                event_type="input",
                timestamp_ms=1_000,
                url="https://example.com/",
                locators=SeleniumLocators(name="email"),
            ),
        )
        assert action.selector is not None
        assert action.selector.css == '[name="email"]'

    def test_xpath_passes_through(self) -> None:
        action = _translate(
            SeleniumEvent(
                event_type="click",
                timestamp_ms=1_000,
                url="https://example.com/",
                locators=SeleniumLocators(xpath="//button[@type='submit']"),
            ),
        )
        assert action.selector is not None
        assert action.selector.xpath == "//button[@type='submit']"

    def test_link_text_becomes_text_content(self) -> None:
        action = _translate(
            SeleniumEvent(
                event_type="click",
                timestamp_ms=1_000,
                url="https://example.com/",
                locators=SeleniumLocators(link_text="Sign in"),
            ),
        )
        assert action.selector is not None
        assert action.selector.text_content == "Sign in"

    def test_aria_attributes_populate_role_and_accessible_name(self) -> None:
        action = _translate(
            SeleniumEvent(
                event_type="click",
                timestamp_ms=1_000,
                url="https://example.com/",
                locators=SeleniumLocators(aria_role="button", aria_label="Save changes"),
            ),
        )
        assert action.selector is not None
        assert action.selector.role == "button"
        assert action.selector.accessible_name == "Save changes"

    def test_test_id_passes_through(self) -> None:
        action = _translate(
            SeleniumEvent(
                event_type="click",
                timestamp_ms=1_000,
                url="https://example.com/",
                locators=SeleniumLocators(test_id="save-btn"),
            ),
        )
        assert action.selector is not None
        assert action.selector.test_id == "save-btn"

    def test_no_locators_yields_none_selector(self) -> None:
        action = _translate(
            SeleniumEvent(
                event_type="click",
                timestamp_ms=1_000,
                url="https://example.com/",
            ),
        )
        assert action.selector is None

    def test_empty_locators_yields_none_selector(self) -> None:
        action = _translate(
            SeleniumEvent(
                event_type="click",
                timestamp_ms=1_000,
                url="https://example.com/",
                locators=SeleniumLocators(),
            ),
        )
        assert action.selector is None

    def test_name_with_quote_is_escaped(self) -> None:
        action = _translate(
            SeleniumEvent(
                event_type="input",
                timestamp_ms=1_000,
                url="https://example.com/",
                locators=SeleniumLocators(name='quote"name'),
            ),
        )
        assert action.selector is not None
        assert action.selector.css == '[name="quote\\"name"]'


class TestContextMapping:
    def test_target_becomes_element_context(self) -> None:
        action = _translate(
            SeleniumEvent(
                event_type="click",
                timestamp_ms=1_000,
                url="https://example.com/",
                target=SeleniumTarget(
                    tag="button",
                    attributes={"type": "submit"},
                    visible_text="Save",
                    bounding_box={"x": 10.0, "y": 20.0, "width": 100.0, "height": 30.0},
                    is_visible=True,
                    is_enabled=True,
                    parent_form_id="checkout",
                    nearby_labels=["Save your work"],
                ),
            ),
        )
        ctx = action.element_context
        assert ctx is not None
        assert ctx.tag == "button"
        assert ctx.attributes == {"type": "submit"}
        assert ctx.visible_text == "Save"
        assert ctx.bounding_box == {"x": 10.0, "y": 20.0, "width": 100.0, "height": 30.0}
        assert ctx.parent_form_id == "checkout"
        assert ctx.nearby_labels == ["Save your work"]

    def test_no_target_yields_none_context(self) -> None:
        action = _translate(
            SeleniumEvent(
                event_type="click",
                timestamp_ms=1_000,
                url="https://example.com/",
            ),
        )
        assert action.element_context is None


class TestEventEnvelope:
    def test_url_and_page_title_pass_through(self) -> None:
        action = _translate(
            SeleniumEvent(
                event_type="click",
                timestamp_ms=1_000,
                url="https://example.com/page",
                page_title="My Page",
                frame_url="https://iframe.example.com/inner",
                viewport={"width": 1280, "height": 800},
            ),
        )
        assert action.url == "https://example.com/page"
        assert action.page_title == "My Page"
        assert action.frame_url == "https://iframe.example.com/inner"
        assert action.viewport == {"width": 1280, "height": 800}

    def test_timestamp_ms_converts_to_utc_datetime(self) -> None:
        action = _translate(
            SeleniumEvent(
                event_type="click",
                timestamp_ms=1_730_000_000_000,
                url="https://example.com/",
            ),
        )
        assert action.timestamp.year == 2024
        assert action.timestamp.tzinfo is not None

    def test_sequence_is_caller_provided(self) -> None:
        translator = SeleniumEventTranslator()
        ev = SeleniumEvent(event_type="click", timestamp_ms=1, url="https://example.com/")
        a = translator.translate(ev, sequence=42)
        assert a.sequence == 42
