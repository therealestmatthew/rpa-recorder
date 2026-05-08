"""Application configuration loaded from `.env` and `RPA_`-prefixed env vars."""

from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    """Runtime configuration for storage paths, classifier thresholds, secrets."""

    database_url: str = "sqlite+aiosqlite:///rpa.db"
    anthropic_api_key: SecretStr | None = None
    classifier_confidence_threshold: float = 0.7

    # LLM classifier (M9).
    llm_model: str = "claude-sonnet-4-6"
    llm_max_concurrency: int = 5
    llm_cache_ttl_s: int = 86400
    llm_daily_budget_usd: float = 5.0
    llm_request_timeout_s: float = 60.0

    # Recovery engine (M10).
    recovery_max_depth: int = 1
    recovery_strategy_timeout_s: float = 10.0
    recovery_llm_timeout_s: float = 30.0

    # Confirmation workflow (M11).
    confirmation_default_filter: str = "below_threshold"
    confirmation_default_mode: str = "per_action"
    confirmation_default_renderer: str = "compact"
    confirmation_audit_bronze: bool = True

    screenshots_dir: Path = Path("screenshots")
    traces_dir: Path = Path("traces")
    recordings_dir: Path = Path("recordings")
    dom_dir: Path = Path("dom")
    storage_state_dir: Path = Path("storage_state")

    # Bronze layer (M6.5+).
    bronze_root: Path = Path("data/bronze")
    bronze_queue_size: int = 1000
    bronze_retention_jsonl_days: int = 30
    bronze_retention_parquet_days: int = 365
    bronze_retention_har_days: int = 90
    bronze_retention_trace_days: int = 90
    bronze_retention_failure_days: int = 30
    bronze_retention_llm_days: int = 365

    default_browser: Literal["chromium"] = "chromium"
    default_headless: bool = False

    # FastAPI control plane (M12).
    redis_url: str = "redis://localhost:6379/0"
    queue_backend: Literal["in_process", "arq"] = "in_process"
    max_queue_depth: int = 100
    rate_limit_per_minute: int = 60
    ws_heartbeat_s: float = 30.0
    ws_event_buffer_size: int = 1000
    api_event_dedup_window: int = 64

    # Medallion silver/gold (M11.5).
    gold_cold_root: Path = Path("data/gold/cold")

    # Workers (M11.5).
    worker_concurrency: int = 5
    worker_replay_max_jobs: int = 2
    worker_medallion_max_jobs: int = 10
    worker_shutdown_timeout: int = 60
    worker_keep_result: int = 3600
    worker_replay_job_timeout: int = 1800

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="RPA_",
        extra="ignore",
    )
