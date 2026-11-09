"""In-memory state for the v0 bot.

This state is intentionally process-local: v0 has no database or Redis and is not a
durable usage ledger. Only successful Telegram deliveries are recorded.
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from backend.core.quota import quota_period_start


@dataclass(frozen=True, slots=True)
class BotV0Config:
    daily_limit: int
    max_height: int
    max_bytes: int
    max_duration_seconds: int
    job_timeout_seconds: int
    media_root: Path
    allowed_user_ids: frozenset[int]
    max_active_jobs_per_user: int


class ActiveJobs:
    def __init__(self, limit: int) -> None:
        self._limit = max(1, limit)
        self._active: dict[int, int] = {}
        self._lock = asyncio.Lock()

    async def acquire(self, user_id: int) -> bool:
        async with self._lock:
            current = self._active.get(user_id, 0)
            if current >= self._limit:
                return False
            self._active[user_id] = current + 1
            return True

    async def release(self, user_id: int) -> None:
        async with self._lock:
            current = self._active.get(user_id, 0)
            if current <= 1:
                self._active.pop(user_id, None)
            else:
                self._active[user_id] = current - 1


class DailyUsage:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self._period: datetime | None = None
        self._counts: dict[int, int] = {}

    def _roll(self, now: datetime) -> None:
        period = quota_period_start(now)
        if period != self._period:
            self._period = period
            self._counts.clear()

    def used(self, user_id: int, *, now: datetime | None = None) -> int:
        self._roll(now or datetime.now(UTC))
        return self._counts.get(user_id, 0)

    def remaining(self, user_id: int, *, now: datetime | None = None) -> int:
        return max(0, self.limit - self.used(user_id, now=now))

    def record(self, user_id: int, *, now: datetime | None = None) -> int:
        self._roll(now or datetime.now(UTC))
        count = self._counts.get(user_id, 0) + 1
        self._counts[user_id] = count
        return count


class RecentUpdates:
    def __init__(self, capacity: int = 500) -> None:
        self._capacity = capacity
        self._order: deque[int] = deque()
        self._seen: set[int] = set()

    def seen(self, update_id: int) -> bool:
        """Return True when this update was already handled; otherwise record it."""
        if update_id in self._seen:
            return True
        self._seen.add(update_id)
        self._order.append(update_id)
        if len(self._order) > self._capacity:
            self._seen.discard(self._order.popleft())
        return False


class BotV0State:
    def __init__(self, config: BotV0Config) -> None:
        self.config = config
        self.jobs = ActiveJobs(config.max_active_jobs_per_user)
        self.usage = DailyUsage(config.daily_limit)
        self.recent_updates = RecentUpdates()

    def is_allowed(self, user_id: int) -> bool:
        return not self.config.allowed_user_ids or user_id in self.config.allowed_user_ids
