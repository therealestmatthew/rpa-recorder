"""`get_config()` — pulls the process-singleton Config from `app.state`."""

from typing import TYPE_CHECKING, cast

from fastapi import Request

if TYPE_CHECKING:
    from rpa_recorder.config import Config


def get_config(request: Request) -> Config:
    """Return the Config instance constructed in `lifespan`."""

    return cast("Config", request.app.state.config)
