"""Per-command dependency factories.

Every command pulls only the factories it needs, keeping unused subsystems
out of cold-start cost (the M9 LLM tier, for example, never spins up the
Anthropic client unless `classify` or `recover` actually run).

Factories that own process-wide singletons (the SQLAlchemy engine, the
session-maker bound to it) are cached at module level. The configuration
object is loaded lazily so tests can monkey-patch `Config()` before the
first call.
"""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from functools import lru_cache
from typing import TYPE_CHECKING

from rpa_recorder.config import Config
from rpa_recorder.medallion import BronzeWriter, LocalFilesystemStore
from rpa_recorder.storage.db import create_engine, get_session, init_db
from rpa_recorder.storage.repositories import BronzeArtifactRepository

if TYPE_CHECKING:
    from anthropic import AsyncAnthropic
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession


@lru_cache(maxsize=1)
def _config() -> Config:
    """Load `Config` once per process. Tests can clear the cache to reload."""
    return Config()


@lru_cache(maxsize=1)
def make_engine() -> AsyncEngine:
    """Return the singleton `AsyncEngine` bound to the configured database URL."""
    return create_engine(_config().database_url)


SessionFactory = Callable[[], AbstractAsyncContextManager["AsyncSession"]]


def make_session_factory() -> SessionFactory:
    """Return a zero-arg callable that yields an `AsyncSession` context manager.

    Commands use it as ``async with session_factory() as db: ...``. The engine
    behind it is cached, so repeated calls within one process share connections.
    """
    engine = make_engine()

    def factory() -> AbstractAsyncContextManager[AsyncSession]:
        return get_session(engine)

    return factory


async def init_database() -> None:
    """Create every declared table on the configured engine. Idempotent."""
    await init_db(make_engine())


BronzeWriterFactory = Callable[["AsyncSession"], BronzeWriter]


def make_bronze_writer_factory() -> BronzeWriterFactory:
    """Return a callable that produces a `BronzeWriter` bound to a session.

    A `BronzeWriter` writes via a `BronzeArtifactRepository`, which in turn
    binds to one `AsyncSession`. Commands construct one writer per session
    boundary, so the factory shape is "give me a writer for this session"
    rather than "give me a singleton."
    """
    cfg = _config()
    store = LocalFilesystemStore(cfg.bronze_root)

    def make_writer(session: AsyncSession) -> BronzeWriter:
        repo = BronzeArtifactRepository(session)
        return BronzeWriter(store, repo)

    return make_writer


def make_anthropic_client() -> AsyncAnthropic:
    """Construct the Anthropic SDK client. Used by M9 (`classify`) and M10."""
    # Lazy import: keeps Anthropic SDK out of cold-start cost for commands
    # that never touch the LLM tier.
    from anthropic import AsyncAnthropic  # noqa: PLC0415

    cfg = _config()
    api_key = cfg.anthropic_api_key.get_secret_value() if cfg.anthropic_api_key else None
    return AsyncAnthropic(api_key=api_key, max_retries=0)


__all__ = [
    "BronzeWriterFactory",
    "SessionFactory",
    "init_database",
    "make_anthropic_client",
    "make_bronze_writer_factory",
    "make_engine",
    "make_session_factory",
]
