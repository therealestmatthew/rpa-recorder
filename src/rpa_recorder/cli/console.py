"""Shared `rich.Console` instance with the project's theme.

Every command renders user-visible output through this single console so the
theme is consistent. Tests can swap it for a `Console(record=True)` to capture
output, but commands themselves must never construct ad-hoc `Console()`s.
"""

from rich.console import Console
from rich.theme import Theme

THEME = Theme(
    {
        "success": "bold green",
        "warning": "yellow",
        "error": "bold red",
        "accent": "cyan",
        "highlight": "magenta",
    }
)

console: Console = Console(theme=THEME)


__all__ = ["THEME", "console"]
