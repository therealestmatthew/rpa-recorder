"""Renderer registry for the M11 confirmation pipeline."""

from typing import TYPE_CHECKING, Any

from rpa_recorder.config import Config
from rpa_recorder.confirmation.renderers.compact import CompactRenderer
from rpa_recorder.confirmation.renderers.detailed import DetailedRenderer
from rpa_recorder.confirmation.renderers.side_by_side import SideBySideRenderer

if TYPE_CHECKING:
    from collections.abc import Callable

    from rpa_recorder.confirmation.protocol import Renderer

_RENDERERS: dict[str, Callable[..., Renderer]] = {
    "compact": CompactRenderer,
    "detailed": DetailedRenderer,
    "side_by_side": SideBySideRenderer,
}


def default_renderers() -> dict[str, Callable[..., Renderer]]:
    """Snapshot of the registry; callers may add or override."""
    return dict(_RENDERERS)


def default_renderer(name: str | None = None, **kwargs: Any) -> Renderer:
    """Construct a renderer from the registry. Defaults to Config setting."""
    resolved = name or Config().confirmation_default_renderer
    cls = _RENDERERS[resolved]
    return cls(**kwargs)


__all__ = [
    "CompactRenderer",
    "DetailedRenderer",
    "SideBySideRenderer",
    "default_renderer",
    "default_renderers",
]
