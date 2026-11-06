import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.core.config import Settings
from backend.database.models import DownloadJob, OutboxEvent, User
from backend.downloads.service import submit_download
from backend.platforms.urls import normalize_url
from backend.workers import tasks


class _FakeRedis:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.jobs: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    async def enqueue_job(self, name: str, *args: Any, **kwargs: Any) -> None:
        if self.fail:
            raise RuntimeError("redis unavailable")
        self.jobs.append((name, args, kwargs))


async def _seed_job(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    settings: Settings,
    now: datetime,
) -> tuple[uuid.UUID, int]:
    async with session_factory() as session:
        user = User(telegram_user_id=uuid.uuid4().int % 10**12)
        session.add(user)
        await session.flush()
        result = await submit_download(
            session,
            user=user,
            normalized_url=normalize_url("https://youtu.be/dQw4w9WgXcQ"),
            idempotency_key=f"outbox:{uuid.uuid4()}",
            now=now,
            settings=settings,
        )
        await session.commit()
        return result.job.id, user.telegram_user_id


async def test_outbox_dispatch_enqueues_each_event_once(
    session_factory: async_sessionmaker[AsyncSession],
    plans: None,
    tmp_path: Path,
) -> None:
    settings = Settings(
        app_env="test",
        free_daily_limit=5,
        premium_daily_limit=100,
        media_root=tmp_path,
    )
    job_id, _ = await _seed_job(session_factory, settings=settings, now=datetime.now(UTC))
    redis = _FakeRedis()
    ctx = {"settings": settings, "session_factory": session_factory, "redis": redis}

    first = await tasks.dispatch_outbox(ctx)
    second = await tasks.dispatch_outbox(ctx)

    assert first == 1
    assert second == 0
    assert len(redis.jobs) == 1
    assert redis.jobs[0][0] == "process_download"
    assert redis.jobs[0][1] == (str(job_id),)
    async with session_factory() as session:
        event = await session.scalar(select(OutboxEvent).where(OutboxEvent.aggregate_id == job_id))
        assert event is not None
        assert event.published_at is not None


async def test_outbox_dispatch_keeps_failed_event_unpublished(
    session_factory: async_sessionmaker[AsyncSession],
    plans: None,
    tmp_path: Path,
) -> None:
    settings = Settings(
        app_env="test",
        free_daily_limit=5,
        premium_daily_limit=100,
        media_root=tmp_path,
        outbox_max_attempts=3,
    )
    job_id, _ = await _seed_job(session_factory, settings=settings, now=datetime.now(UTC))
    ctx = {
        "settings": settings,
        "session_factory": session_factory,
        "redis": _FakeRedis(fail=True),
    }

    published = await tasks.dispatch_outbox(ctx)

    assert published == 0
    async with session_factory() as session:
        event = await session.scalar(select(OutboxEvent).where(OutboxEvent.aggregate_id == job_id))
        assert event is not None
        assert event.published_at is None
        assert event.attempt_count == 1
        assert event.last_error_code == "ENQUEUE_FAILED"
        job = await session.scalar(select(DownloadJob).where(DownloadJob.id == job_id))
        assert job is not None
        assert (
            await session.scalar(
                select(func.count(DownloadJob.id)).where(DownloadJob.user_id == job.user_id)
            )
            == 1
        )
