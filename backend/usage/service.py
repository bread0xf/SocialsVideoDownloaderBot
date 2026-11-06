import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.errors import AppError, ErrorCode
from backend.core.quota import quota_period_start
from backend.database.models import UsageLedger, UsageReservation
from backend.entitlements.service import Entitlement

_ACTIVE_RESERVATION_STATUSES = ("reserved", "committed")


async def lock_user_quota(session: AsyncSession, user_id: uuid.UUID) -> None:
    await session.execute(
        select(func.pg_advisory_xact_lock(func.hashtextextended(str(user_id), 0)))
    )


async def included_usage(
    session: AsyncSession,
    user_id: uuid.UUID,
    entitlement: Entitlement,
    *,
    now: datetime | None = None,
) -> int:
    period = quota_period_start(now or datetime.now(UTC))
    used = await session.scalar(
        select(func.count(UsageReservation.id)).where(
            UsageReservation.user_id == user_id,
            UsageReservation.quota_period_start == period,
            UsageReservation.source == entitlement.quota_source,
            UsageReservation.status.in_(_ACTIVE_RESERVATION_STATUSES),
        )
    )
    return int(used or 0)


async def reserve_quota(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    download_job_id: uuid.UUID,
    entitlement: Entitlement,
    now: datetime | None = None,
) -> UsageReservation:
    now = now or datetime.now(UTC)
    await lock_user_quota(session, user_id)

    existing = await session.scalar(
        select(UsageReservation).where(UsageReservation.download_job_id == download_job_id)
    )
    if existing is not None:
        return existing

    limit = entitlement.daily_included_limit
    if limit is None:
        raise AppError(
            ErrorCode.INTERNAL_ERROR,
            "Downloads on this plan are not available yet.",
        )

    used = await included_usage(session, user_id, entitlement, now=now)
    if used >= limit:
        raise AppError(
            ErrorCode.QUOTA_EXHAUSTED,
            "You have used today's free downloads. Try again after midnight in Lagos.",
        )

    reservation = UsageReservation(
        user_id=user_id,
        download_job_id=download_job_id,
        quota_period_start=quota_period_start(now),
        source=entitlement.quota_source,
        status="reserved",
        reserved_at=now,
        created_at=now,
    )
    session.add(reservation)
    await session.flush()
    return reservation


async def commit_quota(
    session: AsyncSession,
    download_job_id: uuid.UUID,
    *,
    now: datetime | None = None,
) -> UsageReservation | None:
    now = now or datetime.now(UTC)
    reservation = await session.scalar(
        select(UsageReservation)
        .where(UsageReservation.download_job_id == download_job_id)
        .with_for_update()
    )
    if reservation is None:
        return None
    if reservation.status == "released":
        return reservation

    if reservation.status == "reserved":
        reservation.status = "committed"
        reservation.committed_at = now

    await session.execute(
        pg_insert(UsageLedger)
        .values(
            id=uuid.uuid4(),
            user_id=reservation.user_id,
            download_job_id=download_job_id,
            entry_type="download_committed",
            source=reservation.source,
            quantity=1,
            quota_period_start=reservation.quota_period_start,
            idempotency_key=f"download:{download_job_id}:commit",
            created_at=now,
        )
        .on_conflict_do_nothing(index_elements=["idempotency_key"])
    )
    return reservation


async def release_quota(
    session: AsyncSession,
    download_job_id: uuid.UUID,
    *,
    now: datetime | None = None,
) -> UsageReservation | None:
    now = now or datetime.now(UTC)
    reservation = await session.scalar(
        select(UsageReservation)
        .where(UsageReservation.download_job_id == download_job_id)
        .with_for_update()
    )
    if reservation is None:
        return None
    if reservation.status != "reserved":
        return reservation

    reservation.status = "released"
    reservation.released_at = now
    await session.execute(
        pg_insert(UsageLedger)
        .values(
            id=uuid.uuid4(),
            user_id=reservation.user_id,
            download_job_id=download_job_id,
            entry_type="reservation_released",
            source=reservation.source,
            quantity=0,
            quota_period_start=reservation.quota_period_start,
            idempotency_key=f"download:{download_job_id}:release",
            created_at=now,
        )
        .on_conflict_do_nothing(index_elements=["idempotency_key"])
    )
    return reservation
