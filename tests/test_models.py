"""Pydantic data model tests: round-trip serialization, validation, enum coverage."""

from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from rpa_recorder.models import (
    REDACTED_VALUE,
    ActionExecution,
    ActionType,
    ClickPayload,
    ElementContext,
    ElementSelector,
    ExecutionAttempt,
    ExecutionStatus,
    FailureMode,
    InputPayload,
    LLMCall,
    NavigatePayload,
    NetworkEvent,
    ParameterDef,
    RecordedAction,
    Recording,
    RecoveryAction,
    RunResult,
    SelectPayload,
    SemanticIntent,
)


@pytest.fixture
def utcnow() -> datetime:
    return datetime(2026, 5, 4, 12, 0, 0, tzinfo=UTC)


# ---------- enum coverage ----------


class TestEnumCoverage:
    def test_action_type_values(self) -> None:
        expected = {
            "click",
            "input",
            "navigate",
            "select",
            "hover",
            "key_press",
            "scroll",
            "wait",
            "assert",
            "upload",
        }
        assert {a.value for a in ActionType} == expected

    def test_semantic_intent_values(self) -> None:
        expected = {
            "login",
            "search",
            "form_fill",
            "form_submit",
            "navigation",
            "data_extraction",
            "confirmation",
            "dismiss_modal",
            "selection",
            "unknown",
        }
        assert {s.value for s in SemanticIntent} == expected

    def test_execution_status_values(self) -> None:
        expected = {
            "pending",
            "running",
            "success",
            "failed",
            "recovered",
            "skipped",
            "awaiting_confirmation",
        }
        assert {s.value for s in ExecutionStatus} == expected

    def test_failure_mode_values(self) -> None:
        expected = {
            "element_not_found",
            "element_not_interactable",
            "unexpected_modal",
            "navigation_failed",
            "validation_error",
            "timeout",
            "network_error",
            "unknown",
        }
        assert {f.value for f in FailureMode} == expected


# ---------- selector / context ----------


class TestElementSelector:
    def test_all_optional(self) -> None:
        sel = ElementSelector()
        assert sel.role is None
        assert sel.css is None

    def test_round_trip(self) -> None:
        sel = ElementSelector(
            role="button",
            accessible_name="Save",
            test_id="save",
            css="button[data-testid='save']",
        )
        assert ElementSelector.model_validate_json(sel.model_dump_json()) == sel


class TestElementContext:
    def test_defaults(self) -> None:
        ctx = ElementContext(tag="button")
        assert ctx.tag == "button"
        assert ctx.attributes == {}
        assert ctx.is_visible is True
        assert ctx.nearby_labels == []

    def test_round_trip(self) -> None:
        ctx = ElementContext(
            tag="input",
            attributes={"type": "password", "name": "pw"},
            visible_text=None,
            bounding_box={"x": 1.0, "y": 2.0, "w": 100.0, "h": 30.0},
            is_enabled=True,
            parent_form_id="login",
            nearby_labels=["Password"],
        )
        assert ElementContext.model_validate_json(ctx.model_dump_json()) == ctx


# ---------- payload types ----------


class TestPayloads:
    def test_click_default_button(self) -> None:
        p = ClickPayload()
        assert p.button == "left"
        assert p.modifiers == []

    def test_click_invalid_button_raises(self) -> None:
        with pytest.raises(ValidationError):
            ClickPayload(button="green")  # type: ignore[arg-type]

    def test_navigate_default_wait(self) -> None:
        p = NavigatePayload(url="https://example.com")
        assert p.wait_until == "load"

    def test_navigate_invalid_wait_raises(self) -> None:
        with pytest.raises(ValidationError):
            NavigatePayload(url="https://example.com", wait_until="forever")  # type: ignore[arg-type]

    def test_select_requires_values(self) -> None:
        with pytest.raises(ValidationError):
            SelectPayload()  # type: ignore[call-arg]


class TestInputPayloadRedaction:
    def test_plain_value_visible_by_default(self) -> None:
        p = InputPayload(value="hunter2")
        assert p.model_dump()["value"] == "hunter2"

    def test_sensitive_value_visible_without_context(self) -> None:
        p = InputPayload(value="hunter2", is_sensitive=True)
        assert p.model_dump()["value"] == "hunter2"

    def test_sensitive_value_redacted_with_context(self) -> None:
        p = InputPayload(value="hunter2", is_sensitive=True)
        assert p.model_dump(context={"redact_secrets": True})["value"] == REDACTED_VALUE

    def test_non_sensitive_value_not_redacted_with_context(self) -> None:
        p = InputPayload(value="hello", is_sensitive=False)
        assert p.model_dump(context={"redact_secrets": True})["value"] == "hello"

    def test_redaction_via_json_dump(self) -> None:
        p = InputPayload(value="hunter2", is_sensitive=True)
        json_out = p.model_dump_json(context={"redact_secrets": True})
        assert REDACTED_VALUE in json_out
        assert "hunter2" not in json_out

    def test_redaction_propagates_through_recording(self, utcnow: datetime) -> None:
        action = RecordedAction(
            sequence=0,
            timestamp=utcnow,
            action_type=ActionType.INPUT,
            payload=InputPayload(value="hunter2", is_sensitive=True),
            url="https://example.com",
        )
        rec = Recording(
            name="login",
            created_at=utcnow,
            starting_url="https://example.com",
            actions=[action],
        )
        out = rec.model_dump_json(context={"redact_secrets": True})
        assert "hunter2" not in out
        assert REDACTED_VALUE in out


# ---------- recorded action ----------


class TestRecordedAction:
    def test_minimal(self, utcnow: datetime) -> None:
        action = RecordedAction(
            sequence=0,
            timestamp=utcnow,
            action_type=ActionType.CLICK,
            payload=ClickPayload(),
            url="https://example.com",
        )
        assert isinstance(action.id, UUID)
        assert action.semantic_intent == SemanticIntent.UNKNOWN
        assert action.classification_confidence == 0.0
        assert action.frame_url is None

    def test_round_trip_with_input_payload(self, utcnow: datetime) -> None:
        action = RecordedAction(
            sequence=1,
            timestamp=utcnow,
            action_type=ActionType.INPUT,
            payload=InputPayload(value="hello"),
            selector=ElementSelector(test_id="email"),
            element_context=ElementContext(tag="input"),
            url="https://example.com",
            page_title="Sign in",
            frame_url="https://example.com/login",
            viewport={"width": 1280, "height": 800},
        )
        restored = RecordedAction.model_validate_json(action.model_dump_json())
        assert restored == action
        assert isinstance(restored.payload, InputPayload)

    def test_round_trip_with_click_payload(self, utcnow: datetime) -> None:
        action = RecordedAction(
            sequence=0,
            timestamp=utcnow,
            action_type=ActionType.CLICK,
            payload=ClickPayload(button="right", modifiers=["Shift"]),
            url="https://example.com",
        )
        restored = RecordedAction.model_validate_json(action.model_dump_json())
        assert isinstance(restored.payload, ClickPayload)
        assert restored.payload.button == "right"
        assert restored.payload.modifiers == ["Shift"]

    def test_round_trip_with_navigate_payload(self, utcnow: datetime) -> None:
        action = RecordedAction(
            sequence=0,
            timestamp=utcnow,
            action_type=ActionType.NAVIGATE,
            payload=NavigatePayload(url="https://example.com", wait_until="networkidle"),
            url="about:blank",
        )
        restored = RecordedAction.model_validate_json(action.model_dump_json())
        assert isinstance(restored.payload, NavigatePayload)
        assert restored.payload.wait_until == "networkidle"

    def test_round_trip_with_select_payload(self, utcnow: datetime) -> None:
        action = RecordedAction(
            sequence=0,
            timestamp=utcnow,
            action_type=ActionType.SELECT,
            payload=SelectPayload(values=["opt1", "opt2"]),
            url="https://example.com",
        )
        restored = RecordedAction.model_validate_json(action.model_dump_json())
        assert isinstance(restored.payload, SelectPayload)
        assert restored.payload.values == ["opt1", "opt2"]


# ---------- recording ----------


class TestRecording:
    def test_round_trip_empty(self, utcnow: datetime) -> None:
        rec = Recording(
            name="empty",
            created_at=utcnow,
            starting_url="https://example.com",
            actions=[],
        )
        assert Recording.model_validate_json(rec.model_dump_json()) == rec

    def test_round_trip_full(self, utcnow: datetime) -> None:
        action = RecordedAction(
            sequence=0,
            timestamp=utcnow,
            action_type=ActionType.NAVIGATE,
            payload=NavigatePayload(url="https://example.com"),
            url="about:blank",
        )
        net = NetworkEvent(
            timestamp=utcnow,
            method="GET",
            url="https://example.com",
            status=200,
        )
        rec = Recording(
            name="demo",
            description="round-trip test",
            created_at=utcnow,
            created_by="matthew",
            starting_url="about:blank",
            actions=[action],
            network_log=[net],
            parameters={"q": ParameterDef(name="q", type="string", default="hello")},
            tags=["demo", "test"],
        )
        assert Recording.model_validate_json(rec.model_dump_json()) == rec


class TestNetworkEvent:
    def test_minimal(self, utcnow: datetime) -> None:
        evt = NetworkEvent(timestamp=utcnow, method="GET", url="https://example.com")
        assert evt.status is None
        assert evt.request_headers == {}


# ---------- execution ----------


class TestExecutionAttempt:
    def test_round_trip_minimal(self, utcnow: datetime) -> None:
        att = ExecutionAttempt(
            attempt_number=1,
            started_at=utcnow,
            status=ExecutionStatus.SUCCESS,
        )
        assert att.console_log == []
        assert att.js_errors == []
        assert att.accessibility_snapshot_path is None
        assert ExecutionAttempt.model_validate_json(att.model_dump_json()) == att

    def test_round_trip_with_failure(self, utcnow: datetime) -> None:
        att = ExecutionAttempt(
            attempt_number=2,
            started_at=utcnow,
            ended_at=utcnow,
            status=ExecutionStatus.FAILED,
            selector_used=ElementSelector(css="#missing"),
            failure_mode=FailureMode.ELEMENT_NOT_FOUND,
            error_message="locator not found",
            screenshot_path="screenshots/run-1/0_2.png",
            dom_snapshot_path="dom/run-1/0_2.html",
            accessibility_snapshot_path="dom/run-1/0_2.a11y.json",
            console_log=["[warning] something"],
            js_errors=["TypeError: x is undefined"],
        )
        assert ExecutionAttempt.model_validate_json(att.model_dump_json()) == att


class TestRunResult:
    def test_round_trip(self, utcnow: datetime) -> None:
        action_id = UUID("00000000-0000-0000-0000-000000000001")
        recording_id = UUID("00000000-0000-0000-0000-000000000002")
        att = ExecutionAttempt(
            attempt_number=1,
            started_at=utcnow,
            status=ExecutionStatus.SUCCESS,
        )
        execution = ActionExecution(
            action_id=action_id,
            status=ExecutionStatus.SUCCESS,
            attempts=[att],
            duration_ms=42,
        )
        run = RunResult(
            recording_id=recording_id,
            started_at=utcnow,
            status=ExecutionStatus.SUCCESS,
            parameter_values={"q": "hello"},
            executions=[execution],
        )
        assert RunResult.model_validate_json(run.model_dump_json()) == run

    def test_round_trip_with_recovery(self, utcnow: datetime) -> None:
        action_id = UUID("00000000-0000-0000-0000-000000000001")
        recording_id = UUID("00000000-0000-0000-0000-000000000002")
        att = ExecutionAttempt(
            attempt_number=1,
            started_at=utcnow,
            status=ExecutionStatus.RECOVERED,
        )
        recovery = RecoveryAction(
            strategy="llm_reselect",
            rationale="original selector did not resolve",
            succeeded=True,
            new_selector=ElementSelector(test_id="save"),
        )
        execution = ActionExecution(
            action_id=action_id,
            status=ExecutionStatus.RECOVERED,
            attempts=[att],
            recovery=recovery,
        )
        run = RunResult(
            recording_id=recording_id,
            started_at=utcnow,
            status=ExecutionStatus.RECOVERED,
            executions=[execution],
        )
        assert RunResult.model_validate_json(run.model_dump_json()) == run


# ---------- llm call ----------


class TestLLMCall:
    def test_round_trip(self, utcnow: datetime) -> None:
        call = LLMCall(
            called_for="classify",
            model="claude-sonnet-4-6",
            prompt="...",
            response="{}",
            latency_ms=240,
            created_at=utcnow,
            input_tokens=120,
            output_tokens=8,
        )
        assert LLMCall.model_validate_json(call.model_dump_json()) == call

    def test_invalid_called_for_raises(self, utcnow: datetime) -> None:
        with pytest.raises(ValidationError):
            LLMCall(
                called_for="other",  # type: ignore[arg-type]
                model="x",
                prompt="x",
                response="x",
                latency_ms=1,
                created_at=utcnow,
            )


# ---------- parameter def ----------


class TestParameterDef:
    @pytest.mark.parametrize("type_", ["string", "number", "boolean", "secret"])
    def test_valid_types(self, type_: str) -> None:
        p = ParameterDef(name="x", type=type_)  # type: ignore[arg-type]
        assert p.type == type_

    def test_invalid_type_raises(self) -> None:
        with pytest.raises(ValidationError):
            ParameterDef(name="x", type="other")  # type: ignore[arg-type]
