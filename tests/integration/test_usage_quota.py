import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.core.errors import AppError, ErrorCode
from backend.database.models import DownloadJob, UsageLedger, UsageReservation, User
from backend.entitlements.service import Entitlement
from backend.usage.service import (
    commit_quota,
    included_usage,
    release_quota,
    reserve_quota,
)


def _entitlement(*, limit: int = 2) -> Entitlement:
    return Entitlement(
        plan_code="free",
        max_resolution_p=480,
        daily_included_limit=limit,
        quota_source="included",
        priority=0,
        sponsor_eligible=True,
        evaluated_at=datetime.now(UTC),
        subscription_id=None,
        paid_through=None,
    )


async def _user(session: AsyncSession) -> User:
    user = User(telegram_user_id=uuid.uuid4().int % 10**12)
    session.add(user)
    await session.flush()
    return user


async def _job(session: AsyncSession, user: User, key: str) -> DownloadJob:
    job = DownloadJob(
        user_id=user.id,
        platform="youtube",
        submitted_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        status="queued",
        idempotency_key=key,
    )
    session.add(job)
    await session.flush()
    return job


async def test_reservation_limit_commit_and_release(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        user = await _user(session)
        entitlement = _entitlement(limit=2)
        first = await _job(session, user, "first")
        second = await _job(session, user, "second")
        third = await _job(session, user, "third")

        first_reservation = await reserve_quota(
            session, user_id=user.id, download_job_id=first.id, entitlement=entitlement
        )
        await reserve_quota(
            session, user_id=user.id, download_job_id=second.id, entitlement=entitlement
        )
        assert await included_usage(session, user.id, entitlement) == 2

        with pytest.raises(AppError) as exc_info:
            await reserve_quota(
                session, user_id=user.id, download_job_id=third.id, entitlement=entitlement
            )
        assert exc_info.value.code == ErrorCode.QUOTA_EXHAUSTED

        committed = await commit_quota(session, first.id)
        assert committed is not None
        assert committed.status == "committed"
        assert first_reservation.status == "committed"
        assert await included_usage(session, user.id, entitlement) == 2

        released = await release_quota(session, second.id)
        assert released is not None
        assert released.status == "released"
        assert await included_usage(session, user.id, entitlement) == 1

        await reserve_quota(
            session, user_id=user.id, download_job_id=third.id, entitlement=entitlement
        )
        assert await included_usage(session, user.id, entitlement) == 2
        await session.commit()


async def test_commit_and_release_are_idempotent(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        user = await _user(session)
        entitlement = _entitlement(limit=5)
        job = await _job(session, user, "idempotent")

        await reserve_quota(
            session, user_id=user.id, download_job_id=job.id, entitlement=entitlement
        )
        await commit_quota(session, job.id)
        await commit_quota(session, job.id)
        await session.commit()

        ledger_count = await session.scalar(
            select(func.count(UsageLedger.id)).where(
                UsageLedger.idempotency_key == f"download:{job.id}:commit"
            )
        )
        assert ledger_count == 1

        released = await release_quota(session, job.id)
        assert released is not None
        assert released.status == "committed"
        reservation = await session.scalar(
            select(UsageReservation).where(UsageReservation.download_job_id == job.id)
        )
        assert reservation is not None
        assert reservation.status == "committed"


async def test_release_is_idempotent_and_writes_one_ledger_entry(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        user = await _user(session)
        entitlement = _entitlement(limit=5)
        job = await _job(session, user, "release-twice")

        await reserve_quota(
            session, user_id=user.id, download_job_id=job.id, entitlement=entitlement
        )
        await release_quota(session, job.id)
        await release_quota(session, job.id)
        await session.commit()

        ledger_count = await session.scalar(
            select(func.count(UsageLedger.id)).where(
                UsageLedger.idempotency_key == f"download:{job.id}:release"
            )
        )
        assert ledger_count == 1
        assert await included_usage(session, user.id, entitlement) == 0


async def test_missing_premium_allowance_fails_closed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        user = await _user(session)
        entitlement = Entitlement(
            plan_code="premium",
            max_resolution_p=2160,
            daily_included_limit=None,
            quota_source="premium_included",
            priority=10,
            sponsor_eligible=False,
            evaluated_at=datetime.now(UTC),
            subscription_id=None,
            paid_through=None,
        )
        job = await _job(session, user, "premium-unset")

        with pytest.raises(AppError) as exc_info:
            await reserve_quota(
                session, user_id=user.id, download_job_id=job.id, entitlement=entitlement
            )

        assert exc_info.value.code == ErrorCode.INTERNAL_ERROR
        assert (
            await session.scalar(
                select(func.count(UsageReservation.id)).where(UsageReservation.user_id == user.id)
            )
            == 0
        )
