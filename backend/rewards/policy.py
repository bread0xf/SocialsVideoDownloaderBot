from datetime import UTC, datetime, timedelta

from backend.core.config import Settings
from backend.core.quota import next_quota_period_start

REWARD_PROVIDER = "adsun"


def ensure_aware(value: datetime) -> datetime:
    """Reject naive datetimes; a naive value would silently use the host zone."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("reward timestamps must be timezone-aware")
    return value


def reward_transaction_id(
    *,
    telegram_user_id: int,
    block_id: str,
    event_at: datetime,
    provider: str = REWARD_PROVIDER,
) -> str:
    """Synthesize a stable event key because Adsun sends no unique event id.

    Adsun retries the same callback with the same timestamp, so the derived key
    is stable across retries. If the provider sends no timestamp we reject the
    callback rather than risk a duplicate grant. The key is second-resolution:
    two legitimate completions in the same second collapse into one grant.
    """
    instant = ensure_aware(event_at).astimezone(UTC)
    return f"{provider}:{telegram_user_id}:{block_id}:{int(instant.timestamp())}"


def reward_expiry(*, now: datetime, settings: Settings) -> datetime:
    """Return the instant at which a granted credit stops being usable."""
    now = ensure_aware(now).astimezone(UTC)
    if settings.reward_credit_expiry == "ttl":
        seconds = settings.reward_credit_ttl_seconds
        if seconds is None:
            raise ValueError("REWARD_CREDIT_TTL_SECONDS is required when expiry is ttl")
        return now + timedelta(seconds=seconds)
    return next_quota_period_start(now)
