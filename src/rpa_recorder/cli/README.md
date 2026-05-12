# cli

Typer app exposed via the `rpa = "rpa_recorder.cli:app"` entry point (M8 +
M11.5 + M12 additions). One module per subcommand under `commands/`; rich
output formatters under `output/`.

## Layout

```
cli/
├── __init__.py            # re-exports app
├── app.py                 # root Typer instance; registers commands/*.py
├── async_runner.py        # bridges async commands into Typer's sync entry
├── console.py             # shared rich.Console
├── dependencies.py        # shared deps (Config, repository factories)
├── errors.py              # CLIError + handlers; map to exit codes
├── params.py              # reusable typer.Option(...) wrappers
├── commands/              # one file per subcommand
│   ├── record.py          # rpa record
│   ├── replay.py          # rpa replay [--queue]
│   ├── classify.py        # rpa classify
│   ├── confirm.py         # rpa confirm
│   ├── list_recordings.py # rpa list
│   ├── show.py            # rpa show
│   ├── serve.py           # rpa serve (FastAPI control plane)
│   ├── worker.py          # rpa worker --queue {replay|medallion}
│   └── medallion.py       # rpa medallion {promote|compact|status|prune}
└── output/                # rich tables / panels for human-readable output
    ├── recording.py
    └── run.py
```

## Conventions

- **Per-file `B008` ignore.** Typer requires `Option(...)` defaults at
  the function signature; ruff's `B008` disagrees with that pattern. The
  ignore is local to `cli/**` in `pyproject.toml`.
- **Async commands bridge through `async_runner.run(...)`.** The Typer
  callback stays sync; the async core lives in a separate function that
  the runner schedules. Errors propagate as `CLIError` with an exit code.
- **Output goes through `output/`.** Don't `print(...)`; use the rich
  helpers so colors / tables / panels stay consistent. Plain JSON output
  is selected with `--format=json` on commands that support it.
- **Long-running commands respect a queue flag.** `replay` and the
  medallion subcommands support `--queue` so the same operation can run
  in-process (default for ad-hoc CLI use) or enqueue into ARQ (parity
  with the FastAPI control plane).

## Adding a new subcommand

1. Add `commands/<name>.py` exporting a Typer callback.
2. Register in `commands/__init__.py` and import into `app.py`.
3. Reuse `params.py` for shared option shapes.
4. Add a test in `tests/test_cli_<name>.py` using Typer's `CliRunner`.

## See also

- [`docs/m8-cli-commands.md`](../../../docs/m8-cli-commands.md) — milestone doc.
- [`docs/m11.5-workers-and-medallion-promotion.md`](../../../docs/m11.5-workers-and-medallion-promotion.md) — `worker` / `medallion` subcommands.
