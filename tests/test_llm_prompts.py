"""Prompt strategies."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from rpa_recorder.classifier.llm.prompts.classify_v1 import ClassifyV1Prompt
from rpa_recorder.models import (
    REDACTED_VALUE,
    ActionType,
    ElementContext,
    InputPayload,
    RecordedAction,
)

MakeActionFactory = Callable[..., RecordedAction]


def _password_action() -> RecordedAction:
    return RecordedAction(
        sequence=0,
        timestamp=datetime(2026, 5, 4, 12, 0, tzinfo=UTC),
        action_type=ActionType.INPUT,
        payload=InputPayload(value="hunter2", is_sensitive=True),
        element_context=ElementContext(tag="input", attributes={"type": "password"}),
        url="https://example.com/login",
    )


def test_classify_v1_builds_user_message_with_action_context(
    make_action: MakeActionFactory,
) -> None:
    action = make_action(action_type=ActionType.CLICK, url="https://example.com/login")
    surrounding = [action]
    prompt = ClassifyV1Prompt()
    messages, tools = prompt.build(action, surrounding)
    assert isinstance(messages, list)
    assert messages[0]["role"] == "user"
    assert "click" in messages[0]["content"].lower()
    assert tools is not None
    assert tools[0]["name"] == "classify"
    schema = tools[0]["input_schema"]
    assert schema["properties"]["intent"]["type"] == "string"
    assert "login" in schema["properties"]["intent"]["enum"]


def test_classify_v1_redacts_sensitive_payloads() -> None:
    action = _password_action()
    prompt = ClassifyV1Prompt()
    messages, _ = prompt.build(action, [action])
    body = messages[0]["content"]
    assert "hunter2" not in body
    assert REDACTED_VALUE in body


def test_classify_v1_signature_excludes_timestamps() -> None:
    base = _password_action()
    later = base.model_copy(
        update={"timestamp": base.timestamp + timedelta(seconds=300), "id": base.id}
    )
    prompt = ClassifyV1Prompt()
    sig_a = prompt.signature(base, [base])
    sig_b = prompt.signature(later, [later])
    assert sig_a == sig_b


def test_classify_v1_signature_changes_with_payload() -> None:
    a = _password_action()
    b = a.model_copy(update={"payload": InputPayload(value="other", is_sensitive=False)})
    prompt = ClassifyV1Prompt()
    assert prompt.signature(a, [a]) != prompt.signature(b, [b])


def test_classify_v1_signature_changes_with_surrounding_count(
    make_action: MakeActionFactory,
) -> None:
    a = make_action(action_type=ActionType.CLICK)
    b = make_action(sequence=1, action_type=ActionType.NAVIGATE)
    prompt = ClassifyV1Prompt()
    sig_short = prompt.signature(a, [a])
    sig_long = prompt.signature(a, [a, b])
    assert sig_short != sig_long


def test_classify_v1_truncates_long_payload_value(make_action: MakeActionFactory) -> None:
    long_value = "x" * 1000
    action = make_action(
        action_type=ActionType.INPUT,
        payload=InputPayload(value=long_value, is_sensitive=False),
    )
    prompt = ClassifyV1Prompt()
    messages, _ = prompt.build(action, [action])
    assert long_value not in messages[0]["content"]
    assert "…" in messages[0]["content"]
