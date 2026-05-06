"""Response parsers."""

from rpa_recorder.classifier.llm.parsers.free_form import FreeFormParser
from rpa_recorder.classifier.llm.parsers.json_mode import JsonModeParser
from rpa_recorder.classifier.llm.parsers.tool_use import ToolUseParser
from rpa_recorder.classifier.llm.protocol import LLMResponse
from rpa_recorder.models import SemanticIntent


def _response(
    *, text: str | None = None, tool_calls: list[dict[str, object]] | None = None
) -> LLMResponse:
    return LLMResponse(
        text=text,
        tool_calls=tool_calls or [],
        input_tokens=10,
        output_tokens=20,
        stop_reason="end_turn",
        raw={},
    )


# ---- ToolUseParser ----------------------------------------------------------


def test_tool_use_parser_extracts_intent() -> None:
    response = _response(
        tool_calls=[
            {
                "name": "classify",
                "input": {"intent": "login", "confidence": 0.9, "reasoning": "password"},
            }
        ]
    )
    candidate = ToolUseParser().parse(response)
    assert candidate is not None
    assert candidate.intent is SemanticIntent.LOGIN
    assert candidate.confidence == 0.9
    assert candidate.source == "llm"


def test_tool_use_parser_returns_none_on_no_tool_call() -> None:
    response = _response(text="just text", tool_calls=[])
    assert ToolUseParser().parse(response) is None


def test_tool_use_parser_skips_unrelated_tools() -> None:
    response = _response(
        tool_calls=[
            {"name": "other_tool", "input": {"x": 1}},
            {
                "name": "classify",
                "input": {"intent": "search", "confidence": 0.7, "reasoning": "search box"},
            },
        ]
    )
    candidate = ToolUseParser().parse(response)
    assert candidate is not None
    assert candidate.intent is SemanticIntent.SEARCH


def test_tool_use_parser_invalid_intent_returns_none() -> None:
    response = _response(
        tool_calls=[{"name": "classify", "input": {"intent": "not_an_intent", "confidence": 1.0}}]
    )
    assert ToolUseParser().parse(response) is None


def test_tool_use_parser_clamps_confidence() -> None:
    response = _response(
        tool_calls=[{"name": "classify", "input": {"intent": "login", "confidence": 5.0}}]
    )
    candidate = ToolUseParser().parse(response)
    assert candidate is not None
    assert candidate.confidence == 1.0


def test_tool_use_parser_handles_missing_confidence() -> None:
    response = _response(tool_calls=[{"name": "classify", "input": {"intent": "login"}}])
    candidate = ToolUseParser().parse(response)
    assert candidate is not None
    assert candidate.confidence == 0.0
    assert candidate.reasoning == "no reasoning"


# ---- JsonModeParser ---------------------------------------------------------


def test_json_mode_parser_handles_malformed_json() -> None:
    assert JsonModeParser().parse(_response(text="{not json")) is None


def test_json_mode_parser_extracts_intent() -> None:
    response = _response(text='{"intent": "search", "confidence": 0.7, "reasoning": "nav"}')
    candidate = JsonModeParser().parse(response)
    assert candidate is not None
    assert candidate.intent is SemanticIntent.SEARCH


def test_json_mode_parser_rejects_non_object_json() -> None:
    assert JsonModeParser().parse(_response(text='["list"]')) is None


def test_json_mode_parser_returns_none_on_empty_text() -> None:
    assert JsonModeParser().parse(_response(text="")) is None


def test_json_mode_parser_returns_none_on_invalid_intent() -> None:
    response = _response(text='{"intent": "nope", "confidence": 0.5}')
    assert JsonModeParser().parse(response) is None


# ---- FreeFormParser ---------------------------------------------------------


def test_free_form_parser_regex_fallback() -> None:
    response = _response(text="INTENT: login\nCONFIDENCE: 0.85\nREASONING: typed password")
    candidate = FreeFormParser().parse(response)
    assert candidate is not None
    assert candidate.intent is SemanticIntent.LOGIN
    assert candidate.confidence == 0.85


def test_free_form_parser_uses_default_confidence_when_missing() -> None:
    response = _response(text="intent: search")
    candidate = FreeFormParser().parse(response)
    assert candidate is not None
    assert candidate.confidence == 0.5


def test_free_form_parser_returns_none_on_no_intent() -> None:
    assert FreeFormParser().parse(_response(text="random output")) is None


def test_free_form_parser_returns_none_on_invalid_intent() -> None:
    assert FreeFormParser().parse(_response(text="INTENT: not_real")) is None
