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

    default_browser: Literal["chromium"] = "chromium"
    default_headless: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="RPA_",
        extra="ignore",
    )
