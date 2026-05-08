"""Queue seam for the FastAPI control plane.

`api/` depends on `QueuePool` Protocol so M12 ships without ARQ. The default
backend (`InProcessQueuePool`) runs jobs in the FastAPI event loop and
publishes progress to the same Redis pub/sub channels M11.5's worker will use.
M11.5 later adds an `ArqQueuePool` adapter without touching `api/`.
"""

from rpa_recorder.queues.events import publish_progress, subscribe_run
from rpa_recorder.queues.in_process import InProcessQueuePool
from rpa_recorder.queues.protocol import EnqueueResult, JobHandler, QueuePool

__all__ = [
    "EnqueueResult",
    "InProcessQueuePool",
    "JobHandler",
    "QueuePool",
    "publish_progress",
    "subscribe_run",
]
