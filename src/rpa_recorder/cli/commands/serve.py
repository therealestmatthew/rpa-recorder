"""`rpa serve [--port 8000]` — boot the FastAPI control plane."""

import importlib

import typer

from rpa_recorder.cli.app import app
from rpa_recorder.cli.errors import handle_cli_errors


@app.command(name="serve")
@handle_cli_errors
def serve(
    host: str = typer.Option("127.0.0.1", "--host", help="Address to bind."),
    port: int = typer.Option(8000, "--port", help="TCP port to listen on."),
    reload: bool = typer.Option(False, "--reload", help="Auto-reload on source edits."),
) -> None:
    """Boot the FastAPI control plane via uvicorn."""
    uvicorn = importlib.import_module("uvicorn")
    uvicorn.run(
        "rpa_recorder.api:app",
        host=host,
        port=port,
        reload=reload,
    )
