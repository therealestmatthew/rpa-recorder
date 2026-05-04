"""Typer CLI entrypoint. Commands land in milestone 8."""

import typer

app = typer.Typer(
    name="rpa",
    help="Semantic browser RPA: record, classify, replay, and recover.",
    no_args_is_help=True,
)
