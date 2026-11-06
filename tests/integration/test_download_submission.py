import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.core.config import Settings
from backend.core.errors import AppError, ErrorCode
from backend.database.models import DownloadJob, OutboxEvent, UsageReservation, User
from backend.downloads.outbox import EVENT_DOWNLOAD_REQUESTED
from backend.downloads.service import submit_download
from backend.platforms.urls import normalize_url


async def _user(session: AsyncSession) -> User:
    user = User(telegram_user_id=uuid.uuid4().int % 10**12)
    session.add(user)
    await session.flush()
    return user


def _settings() -> Settings:
    return Settings(
        app_env="test",
        free_daily_limit=5,
        free_max_resolution_p=480,
        premium_max_resolution_p=2160,
        premium_daily_limit=100,
        max_active_jobs_per_user=2,
    )


async def test_submission_is_idempotent_and_writes_single_outbox_event(
    session_factory: async_sessionmaker[AsyncSession],
    plans: None,
) -> None:
    now = datetime.now(UTC)
    async with session_factory() as session:
        user = await _user(session)
        normalized = normalize_url("https://youtu.be/dQw4w9WgXcQ?si=tracking")

        first = await submit_download(
            session,
            user=user,
            normalized_url=normalized,
            idempotency_key="telegram:1",
            now=now,
            settings=_settings(),
        )
        second = await submit_download(
            session,
            user=user,
            normalized_url=normalized,
            idempotency_key="telegram:1",
            now=now,
            settings=_settings(),
        )
        await session.commit()

        assert first.created is True
        assert second.created is False
        assert second.job.id == first.job.id
        assert first.job.status == "queued"

        jobs = await session.scalar(
            select(func.count(DownloadJob.id)).where(DownloadJob.user_id == user.id)
        )
        reservations = await session.scalar(
            select(func.count(UsageReservation.id)).where(UsageReservation.user_id == user.id)
        )
        events = await session.scalars(
            select(OutboxEvent).where(OutboxEvent.aggregate_id == first.job.id)
        )
        event_list = list(events)
        assert jobs == 1
        assert reservations == 1
        assert len(event_list) == 1
        assert event_list[0].event_type == EVENT_DOWNLOAD_REQUESTED
        assert event_list[0].payload == {"job_id": str(first.job.id)}


async def test_submission_enforces_active_job_limit(
    session_factory: async_sessionmaker[AsyncSession],
    plans: None,
) -> None:
    now = datetime.now(UTC)
    async with session_factory() as session:
        user = await _user(session)
        normalized = normalize_url("https://www.tiktok.com/@creator/video/1234567890")
        settings = _settings()

        await submit_download(
            session,
            user=user,
            normalized_url=normalized,
            idempotency_key="one",
            now=now,
            settings=settings,
        )
        await submit_download(
            session,
            user=user,
            normalized_url=normalized,
            idempotency_key="two",
            now=now,
            settings=settings,
        )
        await session.commit()

        with pytest.raises(AppError) as exc_info:
            await submit_download(
                session,
                user=user,
                normalized_url=normalized,
                idempotency_key="three",
                now=now,
                settings=settings,
            )

        assert exc_info.value.code == ErrorCode.TEMPORARY_FAILURE
        assert (
            await session.scalar(
                select(func.count(DownloadJob.id)).where(DownloadJob.user_id == user.id)
            )
            == 2
        )


async def test_free_submission_uses_free_media_key_and_reservation_source(
    session_factory: async_sessionmaker[AsyncSession],
    plans: None,
) -> None:
    now = datetime.now(UTC)
    async with session_factory() as session:
        user = await _user(session)
        normalized = normalize_url("https://www.instagram.com/reel/AbCdEf123/")

        result = await submit_download(
            session,
            user=user,
            normalized_url=normalized,
            idempotency_key="free-key",
            now=now,
            settings=_settings(),
        )
        await session.commit()

        reservation = await session.scalar(
            select(UsageReservation).where(UsageReservation.download_job_id == result.job.id)
        )
        assert result.entitlement is not None
        assert result.entitlement.output_profile == "free-480p"
        assert result.job.media_key is not None
        assert reservation is not None
        assert reservation.source == "included"
        assert reservation.status == "reserved"
