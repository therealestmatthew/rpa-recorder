"""`get_session()` — yields an `AsyncSession` per request."""

from typing import TYPE_CHECKING, cast

from fastapi import Request
from sqlalchemy.ext.asyncio import async_sessionmaker

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Open one `AsyncSession` per HTTP request and close it on completion."""
    engine = cast("AsyncEngine", request.app.state.engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
