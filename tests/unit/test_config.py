import pytest
from pydantic import ValidationError

from backend.core.config import Settings


def test_locked_defaults() -> None:
    settings = Settings(_env_file=None, app_env="test")

    assert settings.quota_timezone == "Africa/Lagos"
    assert settings.free_daily_limit == 5
    assert settings.premium_daily_limit == 20
    assert settings.free_max_resolution_p == 480
    assert settings.premium_max_resolution_p == 2160
    assert settings.media_retention_hours == 24


def test_approved_operational_limits() -> None:
    settings = Settings(_env_file=None, app_env="test")

    assert settings.max_media_bytes == 48 * 1024**2
    assert settings.max_media_duration_seconds == 600
    assert settings.worker_concurrency == 2
    assert settings.ffmpeg_timeout_seconds == 600
    assert settings.job_timeout_seconds == 1800
    assert settings.job_max_age_seconds == 7200
    assert settings.media_cache_max_bytes == 50 * 1024**3


def test_invalid_timezone_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_env="test", quota_timezone="Not/AZone")


def test_retention_cannot_exceed_24_hours() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_env="test", media_retention_hours=48)


def test_production_requires_telegram_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_env="production", telegram_bot_token="")
