"""Protocols and value types for the modular LLM classifier.

Five swappable concerns: `LLMBackend` (the wire call), `PromptStrategy`
(message + tool construction), `ResponseParser` (extract a typed candidate),
`RetryPolicy` (around the backend call), and `MergeStrategy` (combine the
heuristic verdict with the LLM verdict in `Classifier`). Plus `ResponseCache`
which is orthogonal to the five.

`ClassifyCandidate` is reused from M7's heuristic protocol (one shape, two
producers). `LLMResponse` is the wire-shape captured from the SDK; the parser
turns it into a `ClassifyCandidate`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, TypeVar

from pydantic import BaseModel, Field

from rpa_recorder.classifier.heuristic.protocol import Classification, ClassifyCandidate

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from rpa_recorder.models import RecordedAction

T = TypeVar("T")


class LLMBudgetExceeded(Exception):  # noqa: N818
    """Raised by `BudgetGuard` when today's spend would exceed the cap.

    Non-retryable: re-raise to the caller, who should treat the action as
    UNKNOWN and move on. The classifier never blocks the batch on a budget
    excursion.
    """


class LLMResponse(BaseModel):
    """Wire-level shape captured from a backend `complete()` call.

    The parser converts this into a typed `ClassifyCandidate`. The `raw`
    field holds the full SDK response so bronze can replay it exactly.
    """

    text: str | None = None
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    input_tokens: int
    output_tokens: int
    stop_reason: str
    raw: dict[str, Any]


class LLMBackend(Protocol):
    """Wire-level model invocation. Backends own retry-disabled SDK clients."""

    name: str
    model: str

    async def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int,
        temperature: float = 0.0,
        timeout_s: float = 60.0,
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse: ...


class PromptStrategy(Protocol):
    """Builds backend messages + tool schema from a `RecordedAction` + neighbours."""

    name: str
    version: str

    def build(
        self,
        action: RecordedAction,
        surrounding: list[RecordedAction],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]] | None]:
        """Return `(messages, tools)`. `tools` is None for non-tool-use prompts."""

    def signature(
        self,
        action: RecordedAction,
        surrounding: list[RecordedAction],
    ) -> str:
        """Stable hash key for caching. MUST exclude timestamps and UUIDs."""


class ResponseParser(Protocol):
    """Translates an `LLMResponse` into a `ClassifyCandidate`. None abstains."""

    name: str

    def parse(self, response: LLMResponse) -> ClassifyCandidate | None: ...


class RetryPolicy(Protocol):
    """Wraps an awaitable callable; only catches the listed `retryable` types."""

    async def execute(
        self,
        fn: Callable[[], Awaitable[T]],
        *,
        retryable: tuple[type[BaseException], ...],
    ) -> T: ...


class MergeStrategy(Protocol):
    """Combines a heuristic candidate and an LLM candidate into a final verdict."""

    name: str

    def merge(
        self,
        heuristic: ClassifyCandidate | None,
        llm: ClassifyCandidate | None,
    ) -> Classification: ...


class ResponseCache(Protocol):
    """Async key/value cache for `LLMResponse` payloads."""

    async def get(self, key: str) -> LLMResponse | None: ...
    async def set(self, key: str, response: LLMResponse, ttl_s: int) -> None: ...


__all__ = [
    "Classification",
    "ClassifyCandidate",
    "LLMBackend",
    "LLMBudgetExceeded",
    "LLMResponse",
    "MergeStrategy",
    "PromptStrategy",
    "ResponseCache",
    "ResponseParser",
    "RetryPolicy",
]
