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

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="RPA_",
        extra="ignore",
    )
