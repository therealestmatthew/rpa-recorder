"""`get_queue_pool()` — returns the process-singleton `QueuePool` from `app.state`."""

from typing import TYPE_CHECKING, cast

from fastapi import Request

if TYPE_CHECKING:
    from rpa_recorder.queues import QueuePool


def get_queue_pool(request: Request) -> QueuePool:
    """Return the QueuePool selected by Config.queue_backend at startup."""

    return cast("QueuePool", request.app.state.queue_pool)
