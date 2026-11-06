from functools import lru_cache
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    log_json: bool = False

    database_url: str = (
        "postgresql+asyncpg://postgres:postgres@localhost:5432/socialsvideodownloaderbot"
    )
    redis_url: str = "redis://localhost:6379/0"

    telegram_bot_token: SecretStr = SecretStr("")
    telegram_polling: bool = True
    telegram_webhook_secret: SecretStr | None = None

    quota_timezone: str = "Africa/Lagos"
    free_daily_limit: int = Field(default=5, ge=1)
    free_max_resolution_p: int = Field(default=480, ge=1)
    premium_max_resolution_p: int = Field(default=2160, ge=1)
    premium_daily_limit: int | None = Field(default=20, ge=1)

    media_root: Path = Path("./storage")
    media_cache_max_bytes: int = Field(default=50 * 1024**3, ge=0)
    media_retention_hours: int = Field(default=24, ge=1, le=24)
    processing_version: str = "1"

    job_timeout_seconds: int = Field(default=1800, ge=1)
    job_max_age_seconds: int = Field(default=7200, ge=60)
    max_media_bytes: int = Field(default=48 * 1024**2, ge=1)
    max_media_duration_seconds: int = Field(default=600, ge=1)
    max_active_jobs_per_user: int = Field(default=2, ge=1)
    worker_concurrency: int = Field(default=2, ge=1)
    telegram_upload_max_bytes: int = Field(default=50 * 1024**2, ge=1)

    extractor_timeout_seconds: int = Field(default=120, ge=1)
    ffmpeg_timeout_seconds: int = Field(default=600, ge=1)
    download_max_attempts: int = Field(default=3, ge=1)
    outbox_poll_interval_seconds: int = Field(default=2, ge=1)
    outbox_max_attempts: int = Field(default=10, ge=1)
    cache_cleanup_interval_seconds: int = Field(default=900, ge=60)

    @field_validator("log_level")
    @classmethod
    def _normalise_log_level(cls, value: str) -> str:
        level = value.upper()
        if level not in _LOG_LEVELS:
            raise ValueError(f"LOG_LEVEL must be one of {sorted(_LOG_LEVELS)}")
        return level

    @field_validator("quota_timezone")
    @classmethod
    def _validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"Unknown QUOTA_TIMEZONE: {value}") from exc
        return value

    @model_validator(mode="after")
    def _validate_production_requirements(self) -> "Settings":
        if self.app_env == "production" and not self.telegram_token:
            raise ValueError("TELEGRAM_BOT_TOKEN is required in production")
        return self

    @property
    def telegram_token(self) -> str:
        return self.telegram_bot_token.get_secret_value()


@lru_cache
def get_settings() -> Settings:
    return Settings()
