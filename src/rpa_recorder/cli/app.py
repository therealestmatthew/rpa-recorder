"""Root Typer app construction + command registration.

Importing `rpa_recorder.cli.commands` triggers each command module's
`@app.command()` decorator at module load time, so by the time `app` is
exposed at the package root every command is registered.

Adding a new command never touches this file: drop a new module under
`commands/`, register it in `commands/__init__.py`, and the import here picks
it up automatically.
"""

import typer

app = typer.Typer(
    name="rpa",
    help="Browser-RPA recorder, classifier, and replayer.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)


# Importing the commands subpackage triggers registration of each command via
# the per-module `@app.command(...)` decorators. Done after `app` is bound so
# the commands can import it.
from rpa_recorder.cli import commands as _commands  # noqa: E402, F401

__all__ = ["app"]
