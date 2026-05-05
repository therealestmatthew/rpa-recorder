"""Three-pipeline engine: filter → normalize → classify.

`HeuristicEngine.process` runs the standard pipeline order with a small twist:
a *post-normalize* filter pass. The full execution order is:

    1. filter       (drops noise on the raw input)
    2. normalize    (cleans surviving actions; may write into `ctx.scratch`)
    3. filter again (consumes scratch — e.g. `drop_coalesced_followers`)
    4. classify     (one verdict per remaining action)

The post-normalize filter pass exists because the per-rule API is
one-action-at-a-time, but coalescing is inherently cross-action: the
`coalesce_input_bursts` normalizer marks follower indices in
`ctx.scratch["coalesce_drops"]`, and the paired `drop_coalesced_followers`
filter consumes that set. Other filters are idempotent — re-running them
either changes nothing (the action is already gone) or finishes the job
that normalization started (e.g. a value trimmed to empty becomes
focus-only and is then dropped). See pitfall #1 in
`docs/m7-heuristic-classifier.md` for the full rationale.

`RuleContext.scratch` is shared across all passes within one `process` call
and reset on the next call. `ctx.actions` is updated to reflect the
post-stage sequence so later rules see the cleaned stream. `ctx.index` is
updated per-iteration so neighbor-aware rules can look back/forward.
"""

from typing import TYPE_CHECKING

import structlog

from rpa_recorder.models import RecordedAction, SemanticIntent

from .protocol import (
    Classification,
    ClassifyRule,
    FilterRule,
    NormalizeRule,
    RuleContext,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

_log = structlog.get_logger(__name__)


class FilterPipeline:
    """Drops actions that any rule rejects (rules AND-ed)."""

    def __init__(self, rules: Sequence[FilterRule]) -> None:
        self._rules: list[FilterRule] = list(rules)

    def apply(
        self,
        actions: list[RecordedAction],
        ctx: RuleContext | None = None,
    ) -> list[RecordedAction]:
        local_ctx = ctx if ctx is not None else RuleContext(actions=list(actions), index=0)
        kept: list[RecordedAction] = []
        for i, action in enumerate(actions):
            local_ctx.index = i
            keep = True
            for rule in self._rules:
                if not rule.apply(action, local_ctx):
                    _log.debug(
                        "action_dropped",
                        rule_name=rule.name,
                        sequence=action.sequence,
                        reason=rule.name,
                    )
                    keep = False
                    break
            if keep:
                kept.append(action)
        return kept


class NormalizePipeline:
    """Threads each action through every rule in order, chaining returns."""

    def __init__(self, rules: Sequence[NormalizeRule]) -> None:
        self._rules: list[NormalizeRule] = list(rules)

    def apply(
        self,
        actions: list[RecordedAction],
        ctx: RuleContext | None = None,
    ) -> list[RecordedAction]:
        local_ctx = ctx if ctx is not None else RuleContext(actions=list(actions), index=0)
        out: list[RecordedAction] = []
        for i, action in enumerate(actions):
            local_ctx.index = i
            current = action
            for rule in self._rules:
                current = rule.apply(current, local_ctx)
            out.append(current)
        return out


class ClassifyPipeline:
    """Runs every rule against one action and picks the highest-confidence verdict.

    Ties broken by registration order (earlier rule wins). When no rule
    produces a candidate, returns `Classification(UNKNOWN, 0.0, ..., "default")`.
    """

    def __init__(self, rules: Sequence[ClassifyRule]) -> None:
        self._rules: list[ClassifyRule] = list(rules)

    def apply(self, action: RecordedAction, ctx: RuleContext) -> Classification:
        best_idx: int | None = None
        best_conf: float = -1.0
        best_intent: SemanticIntent = SemanticIntent.UNKNOWN
        best_reasoning: str = ""
        best_source: str = ""
        for i, rule in enumerate(self._rules):
            candidate = rule.apply(action, ctx)
            if candidate is None:
                continue
            if candidate.confidence > best_conf:
                best_idx = i
                best_conf = candidate.confidence
                best_intent = candidate.intent
                best_reasoning = candidate.reasoning
                best_source = candidate.source
        if best_idx is None:
            return Classification(
                intent=SemanticIntent.UNKNOWN,
                confidence=0.0,
                reasoning="no rule matched",
                source="default",
            )
        return Classification(
            intent=best_intent,
            confidence=best_conf,
            reasoning=best_reasoning,
            source=best_source,
        )


class HeuristicEngine:
    """Filter → Normalize → (post-normalize Filter) → Classify."""

    def __init__(
        self,
        filter_pipeline: FilterPipeline,
        normalize_pipeline: NormalizePipeline,
        classify_pipeline: ClassifyPipeline,
    ) -> None:
        self.filter_pipeline = filter_pipeline
        self.normalize_pipeline = normalize_pipeline
        self.classify_pipeline = classify_pipeline

    def process(self, actions: list[RecordedAction]) -> list[tuple[RecordedAction, Classification]]:
        ctx = RuleContext(actions=list(actions), index=0)

        filtered = self.filter_pipeline.apply(actions, ctx)
        ctx.actions = list(filtered)

        normalized = self.normalize_pipeline.apply(filtered, ctx)
        ctx.actions = list(normalized)

        cleaned = self.filter_pipeline.apply(normalized, ctx)
        ctx.actions = list(cleaned)

        results: list[tuple[RecordedAction, Classification]] = []
        for i, action in enumerate(cleaned):
            ctx.index = i
            verdict = self.classify_pipeline.apply(action, ctx)
            results.append((action, verdict))
        return results
