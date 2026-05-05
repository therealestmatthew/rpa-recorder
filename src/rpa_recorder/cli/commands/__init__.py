"""CLI command modules — each module registers itself on the root `app`.

# Conventions

- One command per module, in this `commands/` package.
- Each module imports `app` from `rpa_recorder.cli.app` and registers its
  command via the `@app.command(...)` decorator at module load time.
- The order of imports below determines the order in `--help` output. It
  mirrors the M8 command catalog: `record`, `list`, `show`, `classify`,
  `replay`, `serve`. The `# isort: skip_file` directive at the top preserves
  that order against ruff/isort's alphabetical sort.
- Async command bodies live in `_<name>_async` helpers and are called via
  `run_async(...)` from the sync wrapper.

# Adding a new command

1. Create `commands/<name>.py` following the per-module shape.
2. Add a `from rpa_recorder.cli.commands import <name>` line below in the
   position you want the command to appear in `--help`.

That is the only edit outside the new file. No existing command needs to know.

# Subcommand groups (convention for M11.5 `medallion`)

For commands that share a namespace — e.g. `rpa medallion promote` — create a
sub-Typer in `commands/medallion/__init__.py` that does
``app.add_typer(medallion_app, name="medallion")``, then register sibling
modules against `medallion_app` rather than the root `app`. Don't pre-build
the sub-Typer in M8: that would force importing M11.5 modules that don't yet
exist.
"""
# isort: skip_file
# ruff: noqa: F401

from rpa_recorder.cli.commands import record
from rpa_recorder.cli.commands import list_recordings
from rpa_recorder.cli.commands import show
from rpa_recorder.cli.commands import classify
from rpa_recorder.cli.commands import replay
from rpa_recorder.cli.commands import serve
