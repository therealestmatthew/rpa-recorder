"""ARQ + Redis worker package (M11.5).

Two worker classes — `ReplayWorkerSettings` (max_jobs=2, replay_queue) and
`MedallionWorkerSettings` (max_jobs=10, medallion_queue) — share the same
job registry and on_startup/on_shutdown hooks. Run them as separate
processes:

    arq rpa_recorder.workers.settings.ReplayWorkerSettings
    arq rpa_recorder.workers.settings.MedallionWorkerSettings

`ArqQueuePool` (in `queues/arq.py`) is the FastAPI-side enqueuer that
talks to the same Redis queue the workers drain.
"""

from rpa_recorder.workers.settings import (
    MedallionWorkerSettings,
    ReplayWorkerSettings,
    WorkerSettings,
)

__all__ = ["MedallionWorkerSettings", "ReplayWorkerSettings", "WorkerSettings"]
