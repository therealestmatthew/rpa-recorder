"""Normalizer pipeline registry. Add a rule by importing it and appending to `default_normalizers()`."""

from typing import TYPE_CHECKING

from .canonicalize_url import CanonicalizeUrl
from .coalesce_input_bursts import CoalesceInputBursts
from .trim_input_value import TrimInputValue

if TYPE_CHECKING:
    from ..protocol import NormalizeRule


def default_normalizers() -> list[NormalizeRule]:
    """Project's curated default normalizer rule set.

    Order matters: trim before coalesce so coalesced bursts compare clean values;
    canonicalize_url is independent of the others.
    """
    return [
        TrimInputValue(),
        CoalesceInputBursts(),
        CanonicalizeUrl(),
    ]


__all__ = [
    "CanonicalizeUrl",
    "CoalesceInputBursts",
    "TrimInputValue",
    "default_normalizers",
]
