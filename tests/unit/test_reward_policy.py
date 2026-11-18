from datetime import UTC, datetime, timedelta, timezone

import pytest

from backend.core.config import Settings
from backend.core.quota import next_quota_period_start
from backend.rewards.policy import (
    ensure_aware,
    reward_expiry,
    reward_transaction_id,
)

NOW = datetime(2026, 11, 17, 21, 30, tzinfo=UTC)


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, app_env="test", **overrides)


def test_transaction_id_is_stable_for_the_same_event() -> None:
    first = reward_transaction_id(telegram_user_id=42, block_id="50001", event_at=NOW)
    second = reward_transaction_id(telegram_user_id=42, block_id="50001", event_at=NOW)

    assert first == second
    assert first == f"adsun:42:50001:{int(NOW.timestamp())}"


def test_transaction_id_changes_for_a_different_event() -> None:
    later = NOW + timedelta(seconds=1)

    assert reward_transaction_id(
        telegram_user_id=42, block_id="50001", event_at=NOW
    ) != reward_transaction_id(telegram_user_id=42, block_id="50001", event_at=later)


def test_transaction_id_includes_the_provider() -> None:
    adsun = reward_transaction_id(
        telegram_user_id=42, block_id="50001", event_at=NOW, provider="adsun"
    )
    other = reward_transaction_id(
        telegram_user_id=42, block_id="50001", event_at=NOW, provider="other"
    )

    assert adsun != other
    assert adsun.startswith("adsun:")
    assert other.startswith("other:")


def test_transaction_id_rejects_naive_datetimes() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        reward_transaction_id(
            telegram_user_id=42,
            block_id="50001",
            event_at=datetime(2026, 11, 17, 21, 30),
        )


def test_transaction_id_normalises_offsets_to_utc() -> None:
    utc_key = reward_transaction_id(telegram_user_id=42, block_id="50001", event_at=NOW)
    offset_key = reward_transaction_id(
        telegram_user_id=42,
        block_id="50001",
        event_at=NOW.astimezone(timezone(timedelta(hours=2))),
    )

    assert offset_key == utc_key


def test_same_second_events_collapse_into_one_key() -> None:
    """Two completions inside one second are indistinguishable to Adsun.

    This is a documented limitation: the provider sends no event id and the
    callback timestamp is second-resolution, so the second event is treated as a
    retry rather than credited again.
    """
    later_in_same_second = NOW + timedelta(milliseconds=400)

    assert reward_transaction_id(
        telegram_user_id=42, block_id="50001", event_at=NOW
    ) == reward_transaction_id(telegram_user_id=42, block_id="50001", event_at=later_in_same_second)


def test_expiry_defaults_to_the_next_quota_day() -> None:
    expires_at = reward_expiry(now=NOW, settings=_settings())

    assert expires_at == next_quota_period_start(NOW)
    assert expires_at > NOW


def test_expiry_just_before_lagos_midnight_is_the_imminent_boundary() -> None:
    just_before = datetime(2026, 11, 17, 22, 59, 59, tzinfo=UTC)

    assert reward_expiry(now=just_before, settings=_settings()) == datetime(
        2026, 11, 17, 23, 0, tzinfo=UTC
    )


def test_expiry_at_lagos_midnight_moves_to_the_next_day() -> None:
    boundary = datetime(2026, 11, 17, 23, 0, tzinfo=UTC)

    assert reward_expiry(now=boundary, settings=_settings()) == datetime(
        2026, 11, 18, 23, 0, tzinfo=UTC
    )


def test_expiry_rejects_naive_now() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        reward_expiry(now=datetime(2026, 11, 17, 21, 30), settings=_settings())


def test_expiry_can_use_a_fixed_ttl() -> None:
    settings = _settings(reward_credit_expiry="ttl", reward_credit_ttl_seconds=600)

    assert reward_expiry(now=NOW, settings=settings) == NOW + timedelta(seconds=600)


def test_ttl_expiry_requires_a_ttl_value() -> None:
    with pytest.raises(ValueError):
        Settings(_env_file=None, app_env="test", reward_credit_expiry="ttl")


def test_ensure_aware_accepts_offset_datetimes() -> None:
    aware = datetime(2026, 11, 17, 21, 30, tzinfo=timezone(timedelta(hours=-3)))

    assert ensure_aware(aware) is aware
