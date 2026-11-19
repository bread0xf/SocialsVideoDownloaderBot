import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

import structlog
from sqlalchemy import ColumnElement, Exists, exists, func, not_, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import Settings, get_settings
from backend.core.quota import next_quota_period_start, quota_period_start
from backend.database.models import (
    RewardEvent,
    RewardSession,
    UsageLedger,
    UsageReservation,
    User,
)
from backend.entitlements.service import resolve_entitlement
from backend.rewards.policy import (
    REWARD_PROVIDER,
    ensure_aware,
    reward_expiry,
    reward_transaction_id,
)
from backend.usage.locking import lock_user_quota

logger = structlog.get_logger(__name__)

REWARD_ENTRY_TYPE = "reward_granted"
REWARD_SOURCE = "reward_credit"
REWARD_SESSION_PENDING = "pending"
REWARD_SESSION_REDEEMED = "redeemed"
REWARD_SESSION_EXPIRED = "expired"
# The provider timestamp is second-resolution; tolerate a small clock/truncation
# gap so an ad completed immediately after serving still matches its session.
_SESSION_EVENT_SKEW = timedelta(seconds=2)
_ACTIVE_RESERVATION_STATUSES = ("reserved", "committed")

RewardStatus = Literal[
    "accepted",
    "duplicate",
    "capped",
    "unknown_user",
    "blocked",
    "premium_ineligible",
    "no_session",
]

RewardEligibility = Literal["eligible", "blocked", "premium_ineligible", "capped"]
RewardAdSessionStatus = Literal["opened", "reused", "blocked", "premium_ineligible", "capped"]


@dataclass(frozen=True, slots=True)
class RewardGrantResult:
    """Outcome of a reward callback.

    Every status except ``duplicate`` describes the durable decision recorded in
    ``reward_events``; callers return HTTP 200 for all of them so the provider
    stops retrying a request that cannot succeed on retry.
    """

    status: RewardStatus
    credits_granted: int = 0


@dataclass(frozen=True, slots=True)
class RewardSessionResult:
    """Result of opening or reusing an ad session."""

    session_id: uuid.UUID
    created: bool
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class RewardAdSessionResult:
    """Result of the bot-facing eligibility + session step.

    ``status`` is either a session outcome (``opened``/``reused``) or the
    advisory rejection reason. Only ``opened`` may fetch an ad.
    """

    status: RewardAdSessionStatus
    session_id: uuid.UUID | None = None
    expires_at: datetime | None = None
    cap_resets_at: datetime | None = None


def _active_reward_reservation() -> Exists:
    """Correlated ``EXISTS`` for a credit consumed by a live reservation."""
    return exists(
        select(UsageReservation.id).where(
            UsageReservation.reward_ledger_id == UsageLedger.id,
            UsageReservation.status.in_(_ACTIVE_RESERVATION_STATUSES),
        )
    )


def _available_credit_filter(now: datetime) -> tuple[ColumnElement[bool], ...]:
    return (
        UsageLedger.entry_type == REWARD_ENTRY_TYPE,
        UsageLedger.source == REWARD_SOURCE,
        or_(UsageLedger.expires_at.is_(None), UsageLedger.expires_at > now),
        not_(_active_reward_reservation()),
    )


async def available_reward_credits(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    now: datetime | None = None,
) -> int:
    """Count usable reward credits: unexpired and not held by a reservation."""
    now = ensure_aware(now or datetime.now(UTC))
    count = await session.scalar(
        select(func.count(UsageLedger.id)).where(
            UsageLedger.user_id == user_id,
            *_available_credit_filter(now),
        )
    )
    return int(count or 0)


async def reserve_reward_credit(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    download_job_id: uuid.UUID,
    now: datetime | None = None,
) -> UsageReservation | None:
    """Reserve the oldest expiring usable credit for a download job.

    The caller must already hold the per-user quota advisory lock so two
    concurrent downloads cannot reserve the same credit.
    """
    now = ensure_aware(now or datetime.now(UTC))
    credit_id = await session.scalar(
        select(UsageLedger.id)
        .where(
            UsageLedger.user_id == user_id,
            *_available_credit_filter(now),
        )
        .order_by(
            UsageLedger.expires_at.asc().nulls_last(),
            UsageLedger.created_at.asc(),
        )
        .limit(1)
        .with_for_update(of=UsageLedger)
    )
    if credit_id is None:
        return None

    reservation = UsageReservation(
        user_id=user_id,
        download_job_id=download_job_id,
        quota_period_start=quota_period_start(now),
        source=REWARD_SOURCE,
        status="reserved",
        reward_ledger_id=credit_id,
        reserved_at=now,
        created_at=now,
    )
    session.add(reservation)
    await session.flush()
    return reservation


async def _expire_stale_sessions(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    provider: str,
    block: str,
    now: datetime,
) -> int:
    """Lazily expire pending sessions for one ad slot before opening a new one."""
    result = await session.execute(
        update(RewardSession)
        .where(
            RewardSession.user_id == user_id,
            RewardSession.provider == provider,
            RewardSession.block == block,
            RewardSession.status == REWARD_SESSION_PENDING,
            RewardSession.expires_at <= now,
        )
        .values(status=REWARD_SESSION_EXPIRED)
        .returning(RewardSession.id)
    )
    expired = len(result.scalars().all())
    if expired:
        logger.info(
            "reward_session_expired",
            provider=provider,
            count=expired,
            reason="ttl_lazy",
        )
    return expired


async def expire_stale_reward_sessions(
    session: AsyncSession,
    *,
    now: datetime | None = None,
) -> int:
    """Expire every pending session past its TTL. Safe to run repeatedly."""
    now = ensure_aware(now or datetime.now(UTC))
    result = await session.execute(
        update(RewardSession)
        .where(
            RewardSession.status == REWARD_SESSION_PENDING,
            RewardSession.expires_at <= now,
        )
        .values(status=REWARD_SESSION_EXPIRED)
        .returning(RewardSession.id)
    )
    expired = len(result.scalars().all())
    if expired:
        logger.info(
            "reward_session_expired",
            provider=REWARD_PROVIDER,
            count=expired,
            reason="ttl_cleanup",
        )
    return expired


async def open_reward_session(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    block: str,
    provider: str = REWARD_PROVIDER,
    now: datetime | None = None,
    settings: Settings | None = None,
) -> RewardSessionResult:
    """Open an ad session, or return the user's existing unexpired one.

    The pending row is the ad cooldown: a second ``/reward`` while it exists
    reuses it and the bot refuses to fetch another ad. The partial unique index
    is the final guard; the per-user advisory lock makes the common path
    deterministic.
    """
    settings = settings or get_settings()
    now = ensure_aware(now or datetime.now(UTC))
    await lock_user_quota(session, user_id)
    await _expire_stale_sessions(
        session,
        user_id=user_id,
        provider=provider,
        block=block,
        now=now,
    )

    existing = await session.scalar(
        select(RewardSession)
        .where(
            RewardSession.user_id == user_id,
            RewardSession.provider == provider,
            RewardSession.block == block,
            RewardSession.status == REWARD_SESSION_PENDING,
            RewardSession.expires_at > now,
        )
        .with_for_update(of=RewardSession)
    )
    if existing is not None:
        logger.info("reward_session_reused", provider=provider)
        return RewardSessionResult(
            session_id=existing.id,
            created=False,
            expires_at=existing.expires_at,
        )

    session_id = uuid.uuid4()
    expires_at = now + timedelta(seconds=settings.reward_session_ttl_seconds)
    inserted = await session.scalar(
        pg_insert(RewardSession)
        .values(
            id=session_id,
            user_id=user_id,
            provider=provider,
            block=block,
            status=REWARD_SESSION_PENDING,
            created_at=now,
            expires_at=expires_at,
        )
        .on_conflict_do_nothing(
            index_elements=["user_id", "provider", "block"],
            index_where=text("status = 'pending'"),
        )
        .returning(RewardSession.id)
    )
    if inserted is None:
        # A concurrent creator won the partial-index race. The advisory lock
        # should prevent this locally, but return its row rather than fail.
        existing = await session.scalar(
            select(RewardSession)
            .where(
                RewardSession.user_id == user_id,
                RewardSession.provider == provider,
                RewardSession.block == block,
                RewardSession.status == REWARD_SESSION_PENDING,
                RewardSession.expires_at > now,
            )
            .with_for_update(of=RewardSession)
        )
        if existing is None:
            raise RuntimeError("reward session conflict without a pending row")
        logger.info("reward_session_reused", provider=provider)
        return RewardSessionResult(
            session_id=existing.id,
            created=False,
            expires_at=existing.expires_at,
        )

    logger.info("reward_session_created", provider=provider)
    return RewardSessionResult(
        session_id=inserted,
        created=True,
        expires_at=expires_at,
    )


async def expire_reward_session(
    session: AsyncSession,
    *,
    session_id: uuid.UUID,
    now: datetime | None = None,
    reason: str = "expired",
) -> bool:
    """Expire one pending session, for example after a failed ad delivery."""
    ensure_aware(now or datetime.now(UTC))
    result = await session.execute(
        update(RewardSession)
        .where(
            RewardSession.id == session_id,
            RewardSession.status == REWARD_SESSION_PENDING,
        )
        .values(status=REWARD_SESSION_EXPIRED)
        .returning(RewardSession.id)
    )
    if result.scalar_one_or_none() is None:
        return False
    logger.info("reward_session_expired", provider=REWARD_PROVIDER, reason=reason)
    return True


async def _record_claim_outcome(
    session: AsyncSession,
    claim_id: uuid.UUID,
    *,
    status: str,
    now: datetime,
    user_id: uuid.UUID | None = None,
    reason_code: str | None = None,
    expires_at: datetime | None = None,
) -> None:
    await session.execute(
        update(RewardEvent)
        .where(RewardEvent.id == claim_id)
        .values(
            status=status,
            user_id=user_id,
            reason_code=reason_code,
            credits_granted=1 if status == "accepted" else 0,
            expires_at=expires_at,
            processed_at=now,
        )
    )


async def _granted_today(session: AsyncSession, user_id: uuid.UUID, period_start: datetime) -> int:
    count = await session.scalar(
        select(func.count(UsageLedger.id)).where(
            UsageLedger.user_id == user_id,
            UsageLedger.entry_type == REWARD_ENTRY_TYPE,
            UsageLedger.source == REWARD_SOURCE,
            UsageLedger.quota_period_start == period_start,
        )
    )
    return int(count or 0)


async def reward_eligibility(
    session: AsyncSession,
    *,
    user: User,
    now: datetime | None = None,
    settings: Settings | None = None,
) -> RewardEligibility:
    """Advisory pre-check mirroring ``grant_reward``'s business rules.

    Used before serving an ad so a user is not shown one that could never be
    credited. The callback re-runs the same checks under the per-user advisory
    lock and remains authoritative; a race here can only over-serve an ad, not
    mint a credit. Released credits still count towards the cap because every
    grant is counted, regardless of reservation settlement.
    """
    settings = settings or get_settings()
    now = ensure_aware(now or datetime.now(UTC))
    if user.is_blocked:
        return "blocked"

    entitlement = await resolve_entitlement(session, user.id, now=now, settings=settings)
    if entitlement.is_premium and not settings.reward_premium_eligible:
        return "premium_ineligible"

    period_start = quota_period_start(now)
    if await _granted_today(session, user.id, period_start) >= settings.reward_daily_cap:
        return "capped"
    return "eligible"


async def open_reward_ad_session(
    session: AsyncSession,
    *,
    user: User,
    block: str,
    provider: str = REWARD_PROVIDER,
    now: datetime | None = None,
    settings: Settings | None = None,
) -> RewardAdSessionResult:
    """Check eligibility, then open or reuse the pending ad session.

    Ineligible users get no session row, so a later callback cannot redeem
    anything. The eligibility check and the insert share this transaction and
    the per-user advisory lock.
    """
    settings = settings or get_settings()
    now = ensure_aware(now or datetime.now(UTC))
    await lock_user_quota(session, user.id)

    eligibility = await reward_eligibility(session, user=user, now=now, settings=settings)
    if eligibility != "eligible":
        cap_resets_at = next_quota_period_start(now) if eligibility == "capped" else None
        logger.info("reward_ad_skipped", provider=provider, reason=eligibility)
        return RewardAdSessionResult(status=eligibility, cap_resets_at=cap_resets_at)

    opened = await open_reward_session(
        session,
        user_id=user.id,
        block=block,
        provider=provider,
        now=now,
        settings=settings,
    )
    return RewardAdSessionResult(
        status="opened" if opened.created else "reused",
        session_id=opened.session_id,
        expires_at=opened.expires_at,
    )


async def grant_reward(
    session: AsyncSession,
    *,
    telegram_user_id: int,
    block_id: str,
    event_at: datetime,
    now: datetime | None = None,
    provider: str = REWARD_PROVIDER,
    settings: Settings | None = None,
) -> RewardGrantResult:
    """Record and process one provider reward callback exactly once.

    The ``reward_events`` row is inserted before any business checks, so the
    unique ``(provider, provider_transaction_id)`` constraint serializes
    concurrent retries. All decisions commit with the grant in one transaction.
    """
    settings = settings or get_settings()
    now = ensure_aware(now or datetime.now(UTC))
    event_at = ensure_aware(event_at)
    transaction_id = reward_transaction_id(
        telegram_user_id=telegram_user_id,
        block_id=block_id,
        event_at=event_at,
        provider=provider,
    )

    claim_id = uuid.uuid4()
    inserted = await session.scalar(
        pg_insert(RewardEvent)
        .values(
            id=claim_id,
            provider=provider,
            provider_transaction_id=transaction_id,
            telegram_user_id=telegram_user_id,
            block_id=block_id,
            provider_event_at=event_at,
            status="pending",
            credits_granted=0,
            received_at=now,
        )
        .on_conflict_do_nothing(index_elements=["provider", "provider_transaction_id"])
        .returning(RewardEvent.id)
    )
    if inserted is None:
        return RewardGrantResult(status="duplicate")

    user = await session.scalar(select(User).where(User.telegram_user_id == telegram_user_id))
    if user is None:
        await _record_claim_outcome(
            session, claim_id, status="unknown_user", now=now, reason_code="unknown_user"
        )
        return RewardGrantResult(status="unknown_user")

    # Serialize cap checks for this user. Same-transaction retries already
    # conflict on the claim key; different events must still not race the cap.
    await lock_user_quota(session, user.id)

    if user.is_blocked:
        await _record_claim_outcome(
            session, claim_id, status="blocked", now=now, user_id=user.id, reason_code="blocked"
        )
        return RewardGrantResult(status="blocked")

    # A callback may only redeem an ad the bot actually served. The row lock
    # serializes concurrent callbacks for the same session; the redemption is
    # written in the same transaction as the credit grant.
    reward_session = await session.scalar(
        select(RewardSession)
        .where(
            RewardSession.user_id == user.id,
            RewardSession.provider == provider,
            RewardSession.block == block_id,
            RewardSession.status == REWARD_SESSION_PENDING,
            RewardSession.expires_at > now,
            RewardSession.created_at <= event_at + _SESSION_EVENT_SKEW,
        )
        .with_for_update(of=RewardSession)
    )
    if reward_session is None:
        await _expire_stale_sessions(
            session,
            user_id=user.id,
            provider=provider,
            block=block_id,
            now=now,
        )
        await _record_claim_outcome(
            session,
            claim_id,
            status="no_session",
            now=now,
            user_id=user.id,
            reason_code="no_session",
        )
        logger.info("reward_callback_no_session", provider=provider)
        return RewardGrantResult(status="no_session")

    entitlement = await resolve_entitlement(session, user.id, now=now, settings=settings)
    if entitlement.is_premium and not settings.reward_premium_eligible:
        await _record_claim_outcome(
            session,
            claim_id,
            status="premium_ineligible",
            now=now,
            user_id=user.id,
            reason_code="premium_ineligible",
        )
        return RewardGrantResult(status="premium_ineligible")

    period_start = quota_period_start(now)
    if await _granted_today(session, user.id, period_start) >= settings.reward_daily_cap:
        await _record_claim_outcome(
            session,
            claim_id,
            status="capped",
            now=now,
            user_id=user.id,
            reason_code="daily_cap",
        )
        return RewardGrantResult(status="capped")

    expires_at = reward_expiry(now=now, settings=settings)
    session.add(
        UsageLedger(
            user_id=user.id,
            entry_type=REWARD_ENTRY_TYPE,
            source=REWARD_SOURCE,
            quantity=1,
            quota_period_start=period_start,
            expires_at=expires_at,
            idempotency_key=f"reward:{transaction_id}:grant",
            created_at=now,
        )
    )
    reward_session.status = REWARD_SESSION_REDEEMED
    reward_session.redeemed_event_id = claim_id
    logger.info("reward_session_redeemed", provider=provider)
    await _record_claim_outcome(
        session,
        claim_id,
        status="accepted",
        now=now,
        user_id=user.id,
        expires_at=expires_at,
    )
    return RewardGrantResult(status="accepted", credits_granted=1)
