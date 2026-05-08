"""`rpa worker [--queue replay|medallion]` — spawn an ARQ worker process.

Thin shell over `arq.worker.run_worker(...)` so users don't have to learn
the `arq <module-path>` invocation. Picks the right `WorkerSettings`
subclass based on `--queue`.
"""

import asyncio

import typer

from rpa_recorder.cli.app import app
from rpa_recorder.cli.errors import handle_cli_errors


@app.command(name="worker")
@handle_cli_errors
def worker(
    queue: str = typer.Option(
        "replay",
        "--queue",
        help="Which queue to drain: 'replay' (browsers) or 'medallion' (compute).",
    ),
) -> None:
    """Spawn an ARQ worker process draining the chosen queue."""
    from arq.worker import create_worker  # noqa: PLC0415

    from rpa_recorder.workers.settings import (  # noqa: PLC0415
        MedallionWorkerSettings,
        ReplayWorkerSettings,
    )

    if queue == "replay":
        queue_name = ReplayWorkerSettings.queue_name
        max_jobs = ReplayWorkerSettings.max_jobs
        worker_obj = create_worker(ReplayWorkerSettings)  # type: ignore[arg-type]
    elif queue == "medallion":
        queue_name = MedallionWorkerSettings.queue_name
        max_jobs = MedallionWorkerSettings.max_jobs
        worker_obj = create_worker(MedallionWorkerSettings)  # type: ignore[arg-type]
    else:
        raise typer.BadParameter(
            f"unknown queue {queue!r}; expected 'replay' or 'medallion'",
            param_hint="--queue",
        )

    typer.echo(f"starting ARQ worker: queue={queue_name} max_jobs={max_jobs}")
    asyncio.run(worker_obj.async_run())
