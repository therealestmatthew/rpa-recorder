"""WebSocket event taxonomy.

Used as the contract for events sent over `/runs/{id}/stream`. The exact
fields vary by `type`; this base model just nails down the always-present
keys so clients can dispatch by `type` without guessing.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class StreamEvent(BaseModel):
    """Always-present envelope on every WebSocket event."""

    event_id: str
    ts: datetime
    type: str
    extra: dict[str, Any] = {}
