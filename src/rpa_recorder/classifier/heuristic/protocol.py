"""Rule contracts and value types for the three-pipeline heuristic engine.

The engine runs three pipelines (filter → normalize → classify) over a list of
`RecordedAction`. Each pipeline calls the rule modules registered under the
matching subpackage. Rules implement one of three Protocols below:

- `FilterRule.apply -> bool` — True keeps, False drops.
- `NormalizeRule.apply -> RecordedAction` — return the (possibly-modified) action.
- `ClassifyRule.apply -> ClassifyCandidate | None` — None abstains.

`RuleContext` is constructed once per `HeuristicEngine.process` call and
threaded through every pipeline within that call. `ctx.scratch` is reset
between calls but **persists across pipelines within a single call** so
cooperating rules — notably `coalesce_input_bursts` (normalizer) handing off
to `drop_coalesced_followers` (filter, run as a post-normalize cleanup) — can
share state.

Confidence convention for classify rules:
    1.00 — the rule is logically equivalent to an `ActionType` (e.g. NAVIGATE).
    0.95 — ground-truth structural signal (e.g. `type=password`).
    0.80-0.90 — strong but not unambiguous signals (role, button text + form).
    0.70 — catch-all for INPUT (shadowed by higher-confidence rules).
Cap rules at 0.95 unless they fall into the 1.00 category.
"""

from typing import Any, Protocol

from pydantic import BaseModel, Field

from rpa_recorder.models import RecordedAction, SemanticIntent


class RuleContext(BaseModel):
    """Information rules might need beyond the action itself.

    Constructed once per `HeuristicEngine.process` call. Rules must treat
    `actions` as read-only; mutate cross-rule state through `scratch`.
    """

    actions: list[RecordedAction]
    index: int
    scratch: dict[str, Any] = Field(default_factory=dict)


class Classification(BaseModel):
    """Final per-action verdict produced by `ClassifyPipeline`."""

    intent: SemanticIntent
    confidence: float
    reasoning: str
    source: str


class ClassifyCandidate(BaseModel):
    """A single rule's verdict; the pipeline picks the highest-confidence one."""

    intent: SemanticIntent
    confidence: float
    reasoning: str
    source: str


class FilterRule(Protocol):
    """Drop-or-keep decision for a single action."""

    name: str

    def apply(self, action: RecordedAction, ctx: RuleContext) -> bool:
        """True keeps, False drops."""


class NormalizeRule(Protocol):
    """In-place-style cleanup of an action; return a new instance via `model_copy`."""

    name: str

    def apply(self, action: RecordedAction, ctx: RuleContext) -> RecordedAction:
        """Return a possibly-modified action; return the input unchanged for a no-op."""


class ClassifyRule(Protocol):
    """Per-action verdict; abstain by returning `None`."""

    name: str

    def apply(self, action: RecordedAction, ctx: RuleContext) -> ClassifyCandidate | None:
        """Return a candidate or None to abstain."""
