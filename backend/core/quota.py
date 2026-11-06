from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

QUOTA_TIMEZONE = ZoneInfo("Africa/Lagos")


def _require_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value


def quota_period_start(now_utc: datetime) -> datetime:
    """Return the current Africa/Lagos calendar-day start as a UTC instant."""
    local = _require_aware(now_utc).astimezone(QUOTA_TIMEZONE)
    start = datetime.combine(local.date(), time.min, tzinfo=QUOTA_TIMEZONE)
    return start.astimezone(UTC)


def next_quota_period_start(now_utc: datetime) -> datetime:
    """Return the next Africa/Lagos calendar-day start as a UTC instant."""
    local = _require_aware(now_utc).astimezone(QUOTA_TIMEZONE)
    next_day = local.date() + timedelta(days=1)
    start = datetime.combine(next_day, time.min, tzinfo=QUOTA_TIMEZONE)
    return start.astimezone(UTC)
