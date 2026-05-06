"""Protocol layer: types are well-formed and `ClassifyCandidate` is reused from M7."""

from rpa_recorder.classifier.heuristic.protocol import ClassifyCandidate as HeuristicCandidate
from rpa_recorder.classifier.llm.protocol import (
    ClassifyCandidate,
    LLMBudgetExceeded,
    LLMResponse,
)


def test_llm_response_round_trips_via_pydantic() -> None:
    payload = LLMResponse(
        text="hi",
        tool_calls=[{"name": "classify", "input": {"intent": "login"}}],
        input_tokens=10,
        output_tokens=20,
        stop_reason="end_turn",
        raw={"id": "msg_1"},
    )
    dumped = payload.model_dump_json()
    rebuilt = LLMResponse.model_validate_json(dumped)
    assert rebuilt.input_tokens == 10
    assert rebuilt.tool_calls[0]["name"] == "classify"
    assert rebuilt.raw["id"] == "msg_1"


def test_classify_candidate_imported_from_m7_not_redefined() -> None:
    # Identity check: if someone redefines `ClassifyCandidate`, this fires.
    assert ClassifyCandidate is HeuristicCandidate


def test_llm_budget_exceeded_is_an_exception() -> None:
    exc = LLMBudgetExceeded("over the cap")
    assert isinstance(exc, Exception)
    assert "over" in str(exc)
