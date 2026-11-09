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
    assert settings.extractor_metadata_timeout_seconds == 60
    assert settings.extractor_download_timeout_seconds == 900
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


def test_v0_token_falls_back_to_primary_token() -> None:
    shared = Settings(_env_file=None, app_env="test", telegram_bot_token="primary")
    dedicated = Settings(
        _env_file=None,
        app_env="test",
        telegram_bot_token="primary",
        telegram_v0_bot_token="v0-token",
    )

    assert shared.telegram_v0_token == "primary"
    assert dedicated.telegram_v0_token == "v0-token"


def test_v0_allow_list_parsing() -> None:
    settings = Settings(_env_file=None, app_env="test", v0_allowed_user_ids=" 1, 2,,3 ")

    assert settings.v0_allowed_user_id_set == frozenset({1, 2, 3})
    assert Settings(_env_file=None, app_env="test").v0_allowed_user_id_set == frozenset()


def test_v0_allow_list_rejects_non_numeric_values() -> None:
    settings = Settings(_env_file=None, app_env="test", v0_allowed_user_ids="1,abc")

    with pytest.raises(ValueError):
        _ = settings.v0_allowed_user_id_set


def test_v0_daily_limit_falls_back_to_free_limit() -> None:
    default = Settings(_env_file=None, app_env="test")
    override = Settings(_env_file=None, app_env="test", v0_daily_limit=9)

    assert default.v0_effective_daily_limit == 5
    assert override.v0_effective_daily_limit == 9


def test_database_url_is_normalised_to_asyncpg() -> None:
    for raw in ("postgres://u:p@h:5432/db", "postgresql://u:p@h:5432/db"):
        settings = Settings(_env_file=None, app_env="test", database_url=raw)

        assert settings.database_url == "postgresql+asyncpg://u:p@h:5432/db"


def test_already_normalised_database_url_is_unchanged() -> None:
    raw = "postgresql+asyncpg://u:p@h:5432/db?ssl=require"

    assert Settings(_env_file=None, app_env="test", database_url=raw).database_url == raw


def test_port_default_and_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PORT", raising=False)

    assert Settings(_env_file=None, app_env="test").port == 8000
    assert Settings(_env_file=None, app_env="test", port=9090).port == 9090
