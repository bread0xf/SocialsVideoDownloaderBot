from datetime import UTC, datetime

from apps.bot_v0.state import ActiveJobs, DailyUsage, RecentUpdates


def test_daily_usage_counts_and_remaining() -> None:
    usage = DailyUsage(limit=2)
    now = datetime(2026, 1, 1, 12, tzinfo=UTC)

    assert usage.used(1, now=now) == 0
    assert usage.remaining(1, now=now) == 2
    assert usage.record(1, now=now) == 1
    assert usage.remaining(1, now=now) == 1
    usage.record(1, now=now)
    assert usage.remaining(1, now=now) == 0


def test_daily_usage_resets_at_lagos_midnight() -> None:
    usage = DailyUsage(limit=5)
    before = datetime(2026, 1, 1, 22, 30, tzinfo=UTC)
    after = datetime(2026, 1, 1, 23, 30, tzinfo=UTC)

    usage.record(7, now=before)

    assert usage.used(7, now=before) == 1
    assert usage.used(7, now=after) == 0


def test_daily_usage_is_per_user() -> None:
    usage = DailyUsage(limit=5)
    now = datetime(2026, 1, 1, 12, tzinfo=UTC)

    usage.record(1, now=now)
    usage.record(1, now=now)

    assert usage.used(1, now=now) == 2
    assert usage.used(2, now=now) == 0


async def test_active_jobs_enforces_limit() -> None:
    jobs = ActiveJobs(limit=1)

    assert await jobs.acquire(1) is True
    assert await jobs.acquire(1) is False
    await jobs.release(1)
    assert await jobs.acquire(1) is True


async def test_active_jobs_allows_different_users() -> None:
    jobs = ActiveJobs(limit=1)

    assert await jobs.acquire(1) is True
    assert await jobs.acquire(2) is True


def test_recent_updates_dedupes_and_bounds_memory() -> None:
    recent = RecentUpdates(capacity=2)

    assert recent.seen(1) is False
    assert recent.seen(1) is True
    assert recent.seen(2) is False
    assert recent.seen(3) is False
    assert recent.seen(1) is False
