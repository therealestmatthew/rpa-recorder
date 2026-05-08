"""Strategy contract + per-call context + verdict shape for the recovery engine.

Five swappable concerns mirror M9: a `Strategy` declares which `FailureMode`s
it applies to and a `cost_tier` (cheap → expensive). Strategies receive a
`RecoveryContext` carrying the shared LLM client / semaphore / bronze writer
and a `BudgetGuard` so total LLM in-flight stays bounded across classification
and recovery. Each `attempt` returns a `RecoveryDecision` describing whether
the precondition matched, whether the page state was actually fixed, and an
optional new `ElementSelector` for the executor to use on retry.

The recovery-tier `SelectorPromptStrategy` and `SelectorResponseParser`
mirror M9's prompt/parser shape but produce an `ElementSelector` rather than
a `ClassifyCandidate`. Sharing the cache + retry + backend lets one event
loop's worth of work stay coordinated.
"""

import asyncio
from typing import TYPE_CHECKING, Any, Protocol

from pydantic import BaseModel, Field

from rpa_recorder.models import ElementSelector, FailureMode

if TYPE_CHECKING:
    from rpa_recorder.classifier.llm.protocol import LLMResponse
    from rpa_recorder.models import RecordedAction


class SelectorPromptStrategy(Protocol):
    """Builds backend messages + tool schema for an `ElementSelector` reselection.

    Mirrors M9's `PromptStrategy` shape but parameterized over selectors.
    The `version` field is part of the cache key so bumping a prompt
    naturally invalidates entries.
    """

    name: str
    version: str

    def build(
        self,
        action: RecordedAction,
        filtered_dom: str,
        failure_mode: FailureMode,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]] | None]:
        """Return `(messages, tools)`. `tools` is None for non-tool-use prompts."""

    def signature(
        self,
        action: RecordedAction,
        filtered_dom: str,
        failure_mode: FailureMode,
    ) -> str:
        """Stable hash key for caching. MUST exclude timestamps and UUIDs."""


class SelectorResponseParser(Protocol):
    """Translates an `LLMResponse` into an `ElementSelector`. None abstains."""

    name: str

    def parse(self, response: LLMResponse) -> ElementSelector | None: ...


class RecoveryContext(BaseModel):
    """Carried into every `Strategy.attempt` call.

    Built once per replay by the executor and reused across all actions in
    the run. The LLM-tier fields are optional: when `llm_backend` is None
    the LLM strategies short-circuit with `applicable=False` rather than
    crashing — useful for offline / no-API-key replays.

    Fields that hold M9 protocol-typed instances (`llm_backend`,
    `llm_retry`, `llm_cache`, `bronze`, `budget`) are typed as `Any` because
    Pydantic v2 does not validate `Protocol` types at runtime; the duck-typed
    contract is enforced at use sites. Static checkers see the proper Protocol
    via the `LLMBackend`, `RetryPolicy`, etc. types in M9.
    """

    model_config = {"arbitrary_types_allowed": True}

    llm_backend: Any = None
    llm_prompt: Any = None
    llm_parser: Any = None
    llm_retry: Any = None
    llm_cache: Any = None
    llm_semaphore: asyncio.Semaphore | None = None
    bronze: Any = None
    budget: Any = None
    max_depth: int = 1


class RecoveryDecision(BaseModel):
    """Strategy verdict. The engine consults `applicable` and `succeeded`."""

    applicable: bool
    succeeded: bool
    new_selector: ElementSelector | None = None
    rationale: str
    artifacts: list[str] = Field(default_factory=list)
    duration_ms: int


class Strategy(Protocol):
    """One recovery move. See `recovery/strategies/*` for implementations."""

    name: str
    applicable_modes: frozenset[FailureMode]
    cost_tier: int

    async def attempt(
        self,
        *,
        failed: Any,
        page: Any,
        original: RecordedAction,
        ctx: RecoveryContext,
    ) -> RecoveryDecision: ...


__all__ = [
    "RecoveryContext",
    "RecoveryDecision",
    "SelectorPromptStrategy",
    "SelectorResponseParser",
    "Strategy",
]
