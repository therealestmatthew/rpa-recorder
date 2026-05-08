"""Standard error envelope for the FastAPI control plane."""

from typing import Any

from pydantic import BaseModel


class ErrorEnvelope(BaseModel):
    """Body of every non-2xx response."""

    error: str
    detail: dict[str, Any] | None = None
