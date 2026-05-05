"""Modular heuristic classifier — three pipelines (filter / normalize / classify).

Public API:

    from rpa_recorder.classifier.heuristic import default_pipeline, classify

    engine = default_pipeline()
    results = engine.process(recording.actions)
    # results: list[tuple[RecordedAction, Classification]]

For one-off lookups without a recording context, the `classify(action)`
convenience runs only the classify pipeline on a single action.

Adding a new rule = a new file under `filters/`, `normalizers/`, or
`classifiers/` plus appending it to the matching `default_*()` registry.
"""

from typing import TYPE_CHECKING

from .classifiers import default_classifiers
from .engine import (
    ClassifyPipeline,
    FilterPipeline,
    HeuristicEngine,
    NormalizePipeline,
)
from .filters import default_filters
from .normalizers import default_normalizers
from .protocol import (
    Classification,
    ClassifyCandidate,
    ClassifyRule,
    FilterRule,
    NormalizeRule,
    RuleContext,
)

if TYPE_CHECKING:
    from rpa_recorder.models import RecordedAction


def default_pipeline() -> HeuristicEngine:
    """Construct the engine with the project's curated default rule set."""
    return HeuristicEngine(
        filter_pipeline=FilterPipeline(default_filters()),
        normalize_pipeline=NormalizePipeline(default_normalizers()),
        classify_pipeline=ClassifyPipeline(default_classifiers()),
    )


def classify(action: RecordedAction) -> Classification:
    """Single-action convenience for callers without a full sequence (tests, REPL).

    Builds a one-element `RuleContext` and runs only the classify pipeline.
    Filter and normalize are skipped since they typically need surrounding context.
    """
    engine = default_pipeline()
    ctx = RuleContext(actions=[action], index=0)
    return engine.classify_pipeline.apply(action, ctx)


__all__ = [
    "Classification",
    "ClassifyCandidate",
    "ClassifyPipeline",
    "ClassifyRule",
    "FilterPipeline",
    "FilterRule",
    "HeuristicEngine",
    "NormalizePipeline",
    "NormalizeRule",
    "RuleContext",
    "classify",
    "default_classifiers",
    "default_filters",
    "default_normalizers",
    "default_pipeline",
]
