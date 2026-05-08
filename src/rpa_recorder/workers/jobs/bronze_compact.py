"""ARQ `compact_bronze_to_parquet` cron job (every 15 min)."""

from typing import Any

import structlog

_log = structlog.get_logger(__name__)


async def compact_bronze_to_parquet(ctx: dict[str, Any]) -> dict[str, Any]:
    """Walk every recording with a JSONL and compact it. No-ops are cheap."""
    from rpa_recorder.config import Config  # noqa: PLC0415
    from rpa_recorder.medallion.compact import compact_all_recordings  # noqa: PLC0415
    from rpa_recorder.storage.db import get_session  # noqa: PLC0415
    from rpa_recorder.storage.repositories import BronzeArtifactRepository  # noqa: PLC0415

    engine = ctx["db_engine"]
    bronze_store = ctx["bronze_store"]
    config: Config = ctx.get("config") or Config()
    log = _log.bind(job_id=ctx.get("job_id"))

    async with get_session(engine) as db:
        repo = BronzeArtifactRepository(db)
        written = await compact_all_recordings(
            bronze_store, repo, parquet_root=config.bronze_root,
        )

    log.info("compact_complete", written=len(written))
    return {"status": "ok", "written": written}
