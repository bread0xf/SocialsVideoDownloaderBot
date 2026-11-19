from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from backend.core.quota import QUOTA_TIMEZONE, next_quota_period_start, quota_period_start

LAGOS = ZoneInfo("Africa/Lagos")

# Africa/Lagos has observed UTC+01:00 year-round since 1919; these dates cover
# both hemispheres' DST transitions and a leap day.
_NO_DST_DATES = (
    datetime(2026, 1, 15, 12, 0, tzinfo=UTC),
    datetime(2026, 3, 29, 12, 0, tzinfo=UTC),
    datetime(2026, 6, 21, 12, 0, tzinfo=UTC),
    datetime(2026, 10, 25, 12, 0, tzinfo=UTC),
    datetime(2028, 2, 29, 12, 0, tzinfo=UTC),
)


def test_period_start_uses_lagos_midnight() -> None:
    now = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)

    assert quota_period_start(now) == datetime(2026, 11, 5, 23, 0, tzinfo=UTC)


def test_lagos_offset_is_constant_across_dst_transitions() -> None:
    for instant in _NO_DST_DATES:
        assert instant.astimezone(LAGOS).utcoffset().total_seconds() == 3600
        start = quota_period_start(instant)
        assert start.astimezone(LAGOS).hour == 0
        assert next_quota_period_start(instant) - start == timedelta(days=1)


def test_period_start_just_before_lagos_midnight() -> None:
    # 22:59:59Z is 23:59:59 in Lagos on 17 November (local day still the 17th).
    now = datetime(2026, 11, 17, 22, 59, 59, tzinfo=UTC)

    assert quota_period_start(now) == datetime(2026, 11, 16, 23, 0, tzinfo=UTC)
    assert next_quota_period_start(now) == datetime(2026, 11, 17, 23, 0, tzinfo=UTC)


def test_period_start_exactly_at_lagos_midnight() -> None:
    # 23:00Z is 00:00 in Lagos on 18 November.
    now = datetime(2026, 11, 17, 23, 0, tzinfo=UTC)

    assert quota_period_start(now) == datetime(2026, 11, 17, 23, 0, tzinfo=UTC)
    assert next_quota_period_start(now) == datetime(2026, 11, 18, 23, 0, tzinfo=UTC)


def test_utc_midnight_is_not_a_quota_boundary() -> None:
    now = datetime(2026, 11, 18, 0, 0, tzinfo=UTC)

    assert quota_period_start(now) == datetime(2026, 11, 17, 23, 0, tzinfo=UTC)


def test_next_period_start() -> None:
    now = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)

    assert next_quota_period_start(now) == datetime(2026, 11, 6, 23, 0, tzinfo=UTC)


def test_offset_aware_input_is_converted_to_lagos_days() -> None:
    now = datetime(2026, 11, 18, 1, 30, tzinfo=ZoneInfo("Europe/Berlin"))

    assert QUOTA_TIMEZONE == LAGOS
    assert quota_period_start(now) == datetime(2026, 11, 17, 23, 0, tzinfo=UTC)


def test_naive_datetime_is_rejected() -> None:
    with pytest.raises(ValueError):
        quota_period_start(datetime(2026, 11, 6, 12, 0))
