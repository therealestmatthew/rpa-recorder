"""`CLIError` - the one exception command bodies use to bail out cleanly.

The decorator `handle_cli_errors` wraps a command body so that any `CLIError`
prints with the `error` style on the shared console and exits with the
exception's `exit_code`. Other exceptions propagate unchanged so unit tests
and bug reports retain full tracebacks.
"""

from functools import wraps
from typing import TYPE_CHECKING

import typer

from rpa_recorder.cli.console import console

if TYPE_CHECKING:
    from collections.abc import Callable


class CLIError(Exception):
    """Raised by command bodies to render a styled error and exit non-zero."""

    def __init__(self, message: str, *, exit_code: int = 1) -> None:
        super().__init__(message)
        self.message = message
        self.exit_code = exit_code


def handle_cli_errors[**P, R](func: Callable[P, R]) -> Callable[P, R]:
    """Decorate a command body so `CLIError` becomes a styled exit."""

    @wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return func(*args, **kwargs)
        except CLIError as exc:
            console.print(f"[error]{exc.message}[/error]")
            raise typer.Exit(code=exc.exit_code) from exc

    return wrapper


__all__ = ["CLIError", "handle_cli_errors"]
