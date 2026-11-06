from datetime import UTC, datetime

import pytest

from backend.core.quota import next_quota_period_start, quota_period_start


def test_period_start_uses_lagos_midnight() -> None:
    now = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)

    assert quota_period_start(now) == datetime(2026, 11, 5, 23, 0, tzinfo=UTC)


def test_period_start_just_after_local_boundary() -> None:
    now = datetime(2026, 11, 6, 0, 0, tzinfo=UTC)

    assert quota_period_start(now) == datetime(2026, 11, 5, 23, 0, tzinfo=UTC)


def test_next_period_start() -> None:
    now = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)

    assert next_quota_period_start(now) == datetime(2026, 11, 6, 23, 0, tzinfo=UTC)


def test_naive_datetime_is_rejected() -> None:
    with pytest.raises(ValueError):
        quota_period_start(datetime(2026, 11, 6, 12, 0))
