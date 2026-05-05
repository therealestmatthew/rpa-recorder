"""Tests for `rpa_recorder.cli.output` renderers."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from rich.console import Console

from rpa_recorder.cli.console import THEME
from rpa_recorder.cli.output import (
    render_recording_detail,
    render_recording_summary,
    render_run_progress,
    render_run_result,
)
from rpa_recorder.models import (
    ActionType,
    ClickPayload,
    ExecutionStatus,
    InputPayload,
    RecordedAction,
    Recording,
    RunResult,
    SemanticIntent,
)
from rpa_recorder.models.execution import ActionExecution, ExecutionAttempt, RecoveryAction
from rpa_recorder.storage.repositories import RecordingSummary


def _capture(renderable: object) -> str:
    # Reuse the project's theme so style names like `accent` resolve.
    console = Console(record=True, width=200, color_system=None, theme=THEME)
    console.print(renderable)
    return console.export_text()


def test_render_recording_summary_includes_action_count() -> None:
    summaries = [
        RecordingSummary(
            id=uuid4(),
            name="login flow",
            created_at=datetime(2026, 5, 4, 12, 0, tzinfo=UTC),
            action_count=7,
        ),
        RecordingSummary(
            id=uuid4(),
            name="checkout",
            created_at=datetime(2026, 5, 3, 9, 0, tzinfo=UTC),
            action_count=12,
        ),
    ]
    out = _capture(render_recording_summary(summaries))
    assert "login flow" in out
    assert "checkout" in out
    assert "7" in out
    assert "12" in out


def test_render_recording_detail_redacts_sensitive_inputs() -> None:
    rec = Recording(
        id=UUID("00000000-0000-0000-0000-000000000001"),
        name="login",
        created_at=datetime(2026, 5, 4, tzinfo=UTC),
        starting_url="https://example.com",
        actions=[
            RecordedAction(
                sequence=0,
                timestamp=datetime(2026, 5, 4, tzinfo=UTC),
                action_type=ActionType.INPUT,
                payload=InputPayload(value="hunter2", is_sensitive=True),
                url="https://example.com",
                semantic_intent=SemanticIntent.LOGIN,
                classification_confidence=0.95,
            ),
        ],
    )
    out = _capture(render_recording_detail(rec, redact=True))
    assert "***REDACTED***" in out
    assert "hunter2" not in out


def test_render_recording_detail_no_redact_shows_value() -> None:
    rec = Recording(
        id=UUID("00000000-0000-0000-0000-000000000002"),
        name="login",
        created_at=datetime(2026, 5, 4, tzinfo=UTC),
        starting_url="https://example.com",
        actions=[
            RecordedAction(
                sequence=0,
                timestamp=datetime(2026, 5, 4, tzinfo=UTC),
                action_type=ActionType.INPUT,
                payload=InputPayload(value="hunter2", is_sensitive=True),
                url="https://example.com",
            ),
        ],
    )
    out = _capture(render_recording_detail(rec, redact=False))
    assert "hunter2" in out


def test_render_recording_detail_renders_click_payload() -> None:
    rec = Recording(
        id=UUID("00000000-0000-0000-0000-000000000003"),
        name="click",
        created_at=datetime(2026, 5, 4, tzinfo=UTC),
        starting_url="https://example.com",
        actions=[
            RecordedAction(
                sequence=0,
                timestamp=datetime(2026, 5, 4, tzinfo=UTC),
                action_type=ActionType.CLICK,
                payload=ClickPayload(button="left"),
                url="https://example.com",
            ),
        ],
    )
    out = _capture(render_recording_detail(rec))
    assert "click" in out


def test_render_run_result_classifies_failure_modes() -> None:
    started = datetime(2026, 5, 4, 12, 0, 0, tzinfo=UTC)
    ended = datetime(2026, 5, 4, 12, 0, 1, tzinfo=UTC)
    rr = RunResult(
        id=UUID("00000000-0000-0000-0000-000000000010"),
        recording_id=UUID("00000000-0000-0000-0000-000000000020"),
        started_at=started,
        ended_at=ended,
        status=ExecutionStatus.FAILED,
        executions=[
            ActionExecution(
                action_id=UUID("00000000-0000-0000-0000-000000000031"),
                status=ExecutionStatus.SUCCESS,
                attempts=[
                    ExecutionAttempt(
                        attempt_number=1,
                        started_at=started,
                        ended_at=ended,
                        status=ExecutionStatus.SUCCESS,
                    )
                ],
                duration_ms=500,
            ),
            ActionExecution(
                action_id=UUID("00000000-0000-0000-0000-000000000032"),
                status=ExecutionStatus.FAILED,
                attempts=[
                    ExecutionAttempt(
                        attempt_number=1,
                        started_at=started,
                        ended_at=ended,
                        status=ExecutionStatus.FAILED,
                    )
                ],
            ),
            ActionExecution(
                action_id=UUID("00000000-0000-0000-0000-000000000033"),
                status=ExecutionStatus.RECOVERED,
                attempts=[
                    ExecutionAttempt(
                        attempt_number=1,
                        started_at=started,
                        ended_at=ended,
                        status=ExecutionStatus.RECOVERED,
                    )
                ],
                recovery=RecoveryAction(strategy="fallback_selector", succeeded=True),
            ),
        ],
    )
    out = _capture(render_run_result(rr))
    assert "success" in out
    assert "failed" in out
    assert "recovered" in out
    assert "fallback_selector" in out


def test_render_run_progress_handles_known_status() -> None:
    out = _capture(render_run_progress({"action_id": "abc", "status": "success", "message": "ok"}))
    assert "abc" in out
    assert "success" in out
    assert "ok" in out


def test_render_run_progress_handles_unknown_shape() -> None:
    out = _capture(render_run_progress({"action_id": "x", "status": "weird-status"}))
    assert "weird-status" in out
