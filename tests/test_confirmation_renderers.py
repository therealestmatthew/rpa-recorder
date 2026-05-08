"""Tests for the M11 confirmation renderers (compact / detailed / side_by_side)."""

from datetime import UTC, datetime
from uuid import uuid4

from rich.console import Console

from rpa_recorder.cli.console import THEME
from rpa_recorder.confirmation import ReviewSummary
from rpa_recorder.confirmation.renderers import (
    CompactRenderer,
    DetailedRenderer,
    SideBySideRenderer,
    default_renderer,
)
from rpa_recorder.models import (
    ActionType,
    ClickPayload,
    ElementContext,
    ElementSelector,
    InputPayload,
    RecordedAction,
    SemanticIntent,
)


def _capture(renderable: object) -> str:
    console = Console(record=True, theme=THEME, width=120, color_system=None)
    console.print(renderable)
    return console.export_text()


def _make_action(
    *,
    visible_text: str | None = None,
    intent: SemanticIntent = SemanticIntent.UNKNOWN,
    confidence: float = 0.4,
    payload: ClickPayload | InputPayload | None = None,
    reasoning: str | None = None,
) -> RecordedAction:
    return RecordedAction(
        sequence=1,
        timestamp=datetime(2026, 5, 6, tzinfo=UTC),
        action_type=ActionType.CLICK
        if isinstance(payload, ClickPayload | type(None))
        else ActionType.INPUT,
        payload=payload or ClickPayload(),
        selector=ElementSelector(test_id="login-btn"),
        element_context=ElementContext(tag="button", visible_text=visible_text),
        url="https://example.com",
        semantic_intent=intent,
        classification_confidence=confidence,
        classification_reasoning=reasoning,
    )


def test_compact_renderer_includes_intent_and_confidence() -> None:
    out = _capture(CompactRenderer().render_action(_make_action(intent=SemanticIntent.LOGIN)))
    assert "intent" in out
    assert "login" in out
    assert "0.40" in out


def test_compact_renderer_truncates_long_visible_text() -> None:
    long_text = "x" * 200
    out = _capture(CompactRenderer().render_action(_make_action(visible_text=long_text)))
    # Truncated to 39 chars + ellipsis (40 total). Verify no full 200-char repeat.
    assert "x" * 200 not in out
    assert "…" in out


def test_compact_renderer_handles_missing_visible_text() -> None:
    out = _capture(CompactRenderer().render_action(_make_action(visible_text=None)))
    assert "—" in out


def test_detailed_renderer_redacts_sensitive_payload() -> None:
    sensitive = InputPayload(value="hunter2", is_sensitive=True)
    out = _capture(DetailedRenderer().render_action(_make_action(payload=sensitive)))
    assert "hunter2" not in out
    assert "REDACTED" in out


def test_side_by_side_parses_heuristic_and_llm_markers() -> None:
    reasoning = "[heuristic:login_rule] matched form ; [llm] override SEARCH"
    out = _capture(SideBySideRenderer().render_action(_make_action(reasoning=reasoning)))
    assert "login_rule" in out
    assert "override SEARCH" in out


def test_side_by_side_handles_missing_markers() -> None:
    out = _capture(SideBySideRenderer().render_action(_make_action(reasoning=None)))
    assert "—" in out


def test_renderer_summary_columns_present() -> None:
    summary = ReviewSummary(
        recording_id=uuid4(),
        total_candidates=2,
        accepted=1,
        relabeled=1,
        skipped=0,
        duration_s=1.25,
    )
    out = _capture(CompactRenderer().render_summary(summary))
    assert "candidates" in out
    assert "accepted" in out
    assert "relabeled" in out


def test_default_renderer_is_compact() -> None:
    assert isinstance(default_renderer(), CompactRenderer)
