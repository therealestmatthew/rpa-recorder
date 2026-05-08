"""M11 confirmation pipeline: pluggable filters, review modes, renderers.

Public API mirrors M9 (`classifier/llm`) and M10 (`recovery`):

- `ConfirmationRunner` orchestrates one `rpa confirm <id>` pass.
- `default_runner(...)` constructs from registry names defaulted to Config.
- The protocol layer (`Filter`, `ReviewMode`, `Renderer`) defines the
  three plugin axes; their per-rule modules live in `filters/`, `modes/`,
  `renderers/`.
"""

from rpa_recorder.confirmation.filters import default_filter, default_filters
from rpa_recorder.confirmation.modes import default_mode, default_modes
from rpa_recorder.confirmation.protocol import (
    ActionReviewResult,
    Decision,
    Filter,
    OnDecision,
    Renderer,
    ReviewMode,
    ReviewSummary,
)
from rpa_recorder.confirmation.renderers import default_renderer, default_renderers
from rpa_recorder.confirmation.runner import ConfirmationRunner, default_runner

__all__ = [
    "ActionReviewResult",
    "ConfirmationRunner",
    "Decision",
    "Filter",
    "OnDecision",
    "Renderer",
    "ReviewMode",
    "ReviewSummary",
    "default_filter",
    "default_filters",
    "default_mode",
    "default_modes",
    "default_renderer",
    "default_renderers",
    "default_runner",
]
