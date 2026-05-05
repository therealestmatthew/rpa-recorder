"""Run async functions from sync Typer commands.

Typer dispatches command callbacks synchronously. `run_async` wraps an async
callable as a sync callable that drives the coroutine via `asyncio.run`. It
also translates `KeyboardInterrupt` and `asyncio.CancelledError` into a clean
`CLIError("interrupted", exit_code=130)` so commands' `try/finally` teardown
runs before the process exits.
"""

import asyncio
from functools import wraps
from typing import TYPE_CHECKING

from rpa_recorder.cli.errors import CLIError

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine


def run_async[**P, T](coro_fn: Callable[P, Coroutine[object, object, T]]) -> Callable[P, T]:
    """Decorate an async function so Typer can call it directly.

    Wraps `asyncio.run(coro_fn(*args, **kwargs))` with KeyboardInterrupt
    translated to a clean `CLIError("interrupted")` so commands can rely on
    their `try/finally` blocks running before the process exits.
    """

    @wraps(coro_fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        try:
            return asyncio.run(coro_fn(*args, **kwargs))
        except KeyboardInterrupt as exc:
            raise CLIError("interrupted", exit_code=130) from exc
        except asyncio.CancelledError as exc:
            raise CLIError("interrupted", exit_code=130) from exc

    return wrapper


__all__ = ["run_async"]
