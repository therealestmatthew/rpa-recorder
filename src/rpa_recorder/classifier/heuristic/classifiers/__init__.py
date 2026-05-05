"""Classifier pipeline registry. Add a rule by importing it and appending to `default_classifiers()`.

Order matters only for tie-breaking: when two rules return identical
confidence, the rule that appears first wins. Confidence dominates whenever
values differ.
"""

from typing import TYPE_CHECKING

from .confirmation import ConfirmationClassifier
from .dismiss_modal import DismissModalClassifier
from .form_fill import FormFillClassifier
from .form_submit import FormSubmitClassifier
from .login import LoginClassifier
from .navigation import NavigationClassifier
from .search import SearchClassifier

if TYPE_CHECKING:
    from ..protocol import ClassifyRule


def default_classifiers() -> list[ClassifyRule]:
    """Project's curated default classifier rule set.

    Listed in descending confidence (NavigationClassifier sits last because it
    only fires on NAVIGATE — `action_type` already disambiguates it from any
    other rule, so its position doesn't change behavior).
    """
    return [
        LoginClassifier(),
        SearchClassifier(),
        FormSubmitClassifier(),
        ConfirmationClassifier(),
        DismissModalClassifier(),
        NavigationClassifier(),
        FormFillClassifier(),
    ]


__all__ = [
    "ConfirmationClassifier",
    "DismissModalClassifier",
    "FormFillClassifier",
    "FormSubmitClassifier",
    "LoginClassifier",
    "NavigationClassifier",
    "SearchClassifier",
    "default_classifiers",
]
