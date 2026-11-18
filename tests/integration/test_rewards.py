import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.api.app import create_app
from backend.core.config import Settings
from backend.core.errors import AppError, ErrorCode
from backend.core.quota import next_quota_period_start, quota_period_start
from backend.database.models import (
    DownloadJob,
    Plan,
    RewardEvent,
    RewardSession,
    Subscription,
    UsageLedger,
    User,
)
from backend.entitlements.service import Entitlement
from backend.rewards.policy import REWARD_PROVIDER
from backend.rewards.service import (
    REWARD_ENTRY_TYPE,
    REWARD_SESSION_EXPIRED,
    REWARD_SESSION_PENDING,
    REWARD_SESSION_REDEEMED,
    RewardSessionResult,
    available_reward_credits,
    expire_stale_reward_sessions,
    grant_reward,
    open_reward_ad_session,
    open_reward_session,
)
from backend.usage.service import commit_quota, release_quota, reserve_quota

SECRET = "s" * 40
BLOCK = "50001"


@pytest.fixture(autouse=True)
def _do_not_reconfigure_global_logging(monkeypatch: pytest.MonkeyPatch) -> None:
    """Creating the app normally reconfigures structlog for the whole process.

    That leaks into unrelated tests (``capture_logs`` stops capturing once a
    logger is cached), so keep this module's app construction side-effect free.
    """
    monkeypatch.setattr("backend.api.app.configure_logging", lambda *args, **kwargs: None)


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_env": "test",
        "adsun_enabled": True,
        "adsun_block_id": BLOCK,
        "adsun_reward_secret": SECRET,
        "reward_daily_cap": 10,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def _callback_url(*, user_id: int, ts: int, block: str = BLOCK, secret: str = SECRET) -> str:
    return f"/api/v1/rewards/adsun/callback?userid={user_id}&block={block}&secret={secret}&ts={ts}"


def _app_client(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> httpx.AsyncClient:
    app = create_app(settings)
    app.state.session_factory = session_factory
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def _user(
    session: AsyncSession, *, telegram_user_id: int | None = None, blocked: bool = False
) -> User:
    user = User(
        telegram_user_id=telegram_user_id or uuid.uuid4().int % 10**12,
        is_blocked=blocked,
    )
    session.add(user)
    await session.flush()
    return user


async def _premium_user(session: AsyncSession) -> User:
    user = await _user(session)
    plan = await session.scalar(select(Plan).where(Plan.code == "premium"))
    assert plan is not None
    session.add(
        Subscription(
            user_id=user.id,
            plan_id=plan.id,
            provider="manual",
            status="active",
            started_at=datetime.now(UTC) - timedelta(days=1),
            paid_through=datetime.now(UTC) + timedelta(days=30),
        )
    )
    await session.flush()
    return user


async def _grants(session: AsyncSession, user_id: uuid.UUID) -> int:
    return int(
        await session.scalar(
            select(func.count(UsageLedger.id)).where(
                UsageLedger.user_id == user_id,
                UsageLedger.entry_type == REWARD_ENTRY_TYPE,
            )
        )
        or 0
    )


def _entitlement(*, limit: int) -> Entitlement:
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


async def _job(session: AsyncSession, user: User, key: str) -> uuid.UUID:
    job = DownloadJob(
        user_id=user.id,
        platform="youtube",
        submitted_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        status="queued",
        idempotency_key=key,
    )
    session.add(job)
    await session.flush()
    return job.id


async def _open_session(
    session: AsyncSession,
    user: User,
    *,
    now: datetime,
    block: str = BLOCK,
    settings: Settings | None = None,
) -> RewardSessionResult:
    return await open_reward_session(
        session,
        user_id=user.id,
        provider=REWARD_PROVIDER,
        block=block,
        now=now,
        settings=settings or _settings(),
    )


async def _grant_status(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    user_id: uuid.UUID,
    telegram_user_id: int,
    event_at: datetime,
    now: datetime,
    settings: Settings,
    block: str = BLOCK,
    open_session: bool = True,
) -> str:
    async with session_factory() as session:
        if open_session:
            await open_reward_session(
                session,
                user_id=user_id,
                provider=REWARD_PROVIDER,
                block=block,
                now=now,
                settings=settings,
            )
        result = await grant_reward(
            session,
            telegram_user_id=telegram_user_id,
            block_id=block,
            event_at=event_at,
            now=now,
            settings=settings,
        )
        await session.commit()
        return result.status


async def test_valid_callback_redeems_the_session_and_grants_one_credit(
    session_factory: async_sessionmaker[AsyncSession], plans: None
) -> None:
    now = datetime.now(UTC)
    async with session_factory() as session:
        user = await _user(session)
        opened = await _open_session(session, user, now=now)
        await session.commit()
        telegram_user_id = user.telegram_user_id
        user_id = user.id

    ts = int(now.timestamp())
    async with _app_client(_settings(), session_factory) as client:
        response = await client.get(_callback_url(user_id=telegram_user_id, ts=ts))

    assert response.status_code == 200
    assert response.text == "accepted"
    assert response.headers["cache-control"] == "no-store"

    async with session_factory() as session:
        credit = await session.scalar(
            select(UsageLedger).where(
                UsageLedger.user_id == user_id,
                UsageLedger.entry_type == REWARD_ENTRY_TYPE,
            )
        )
        assert credit is not None
        assert credit.source == "reward_credit"
        assert credit.quantity == 1
        assert credit.quota_period_start == quota_period_start(datetime.now(UTC))
        assert credit.expires_at == next_quota_period_start(datetime.now(UTC))
        assert credit.idempotency_key == f"reward:adsun:{telegram_user_id}:{BLOCK}:{ts}:grant"

        event = await session.scalar(
            select(RewardEvent).where(
                RewardEvent.provider_transaction_id.like(f"adsun:{telegram_user_id}:%")
            )
        )
        assert event is not None
        assert event.status == "accepted"
        assert event.user_id == user_id
        assert event.credits_granted == 1
        assert event.processed_at is not None

        reward_session = await session.scalar(
            select(RewardSession).where(RewardSession.id == opened.session_id)
        )
        assert reward_session is not None
        assert reward_session.status == REWARD_SESSION_REDEEMED
        assert reward_session.redeemed_event_id == event.id


async def test_duplicate_callback_does_not_double_credit(
    session_factory: async_sessionmaker[AsyncSession], plans: None
) -> None:
    now = datetime.now(UTC)
    async with session_factory() as session:
        user = await _user(session)
        await _open_session(session, user, now=now)
        await session.commit()
        telegram_user_id = user.telegram_user_id
        user_id = user.id

    ts = int(now.timestamp())
    async with _app_client(_settings(), session_factory) as client:
        first = await client.get(_callback_url(user_id=telegram_user_id, ts=ts))
        second = await client.get(_callback_url(user_id=telegram_user_id, ts=ts))

    assert first.text == "accepted"
    assert second.status_code == 200
    assert second.text == "duplicate"

    async with session_factory() as session:
        assert await _grants(session, user_id) == 1
        assert (
            await session.scalar(
                select(func.count(RewardEvent.id)).where(
                    RewardEvent.telegram_user_id == telegram_user_id
                )
            )
            == 1
        )


async def test_callback_stops_at_the_daily_cap(
    session_factory: async_sessionmaker[AsyncSession], plans: None
) -> None:
    now = datetime.now(UTC)
    async with session_factory() as session:
        user = await _user(session)
        await _open_session(session, user, now=now)
        await session.commit()
        telegram_user_id = user.telegram_user_id
        user_id = user.id

    ts = int(now.timestamp())
    async with _app_client(_settings(reward_daily_cap=1), session_factory) as client:
        first = await client.get(_callback_url(user_id=telegram_user_id, ts=ts))

        # A real second ad view creates a fresh session after the first redeem.
        async with session_factory() as session:
            user = await session.get(User, user_id)
            assert user is not None
            await _open_session(session, user, now=now + timedelta(seconds=1))
            await session.commit()

        # The event timestamp must not predate the session it redeems.
        second = await client.get(_callback_url(user_id=telegram_user_id, ts=ts + 2))

    assert first.text == "accepted"
    assert second.status_code == 200
    assert second.text == "capped"

    async with session_factory() as session:
        assert await _grants(session, user_id) == 1
        capped = await session.scalar(
            select(RewardEvent)
            .where(RewardEvent.telegram_user_id == telegram_user_id)
            .order_by(RewardEvent.received_at.desc())
        )
        assert capped is not None
        assert capped.status == "capped"
        assert capped.credits_granted == 0
        assert capped.reason_code == "daily_cap"


async def test_unknown_user_is_recorded_without_a_grant(
    session_factory: async_sessionmaker[AsyncSession], plans: None
) -> None:
    ts = int(datetime.now(UTC).timestamp())
    unknown = 999_000_000 + uuid.uuid4().int % 1000

    async with _app_client(_settings(), session_factory) as client:
        response = await client.get(_callback_url(user_id=unknown, ts=ts))

    assert response.status_code == 200
    assert response.text == "unknown_user"

    async with session_factory() as session:
        event = await session.scalar(
            select(RewardEvent).where(
                RewardEvent.provider_transaction_id.like(f"adsun:{unknown}:%")
            )
        )
        assert event is not None
        assert event.status == "unknown_user"
        assert event.user_id is None
        assert event.credits_granted == 0
        assert await session.scalar(select(func.count(UsageLedger.id))) == 0


async def test_premium_users_do_not_earn_by_default(
    session_factory: async_sessionmaker[AsyncSession], plans: None
) -> None:
    now = datetime.now(UTC)
    async with session_factory() as session:
        user = await _premium_user(session)
        await _open_session(session, user, now=now)
        await session.commit()
        telegram_user_id = user.telegram_user_id
        user_id = user.id

    ts = int(now.timestamp())
    async with _app_client(_settings(), session_factory) as client:
        response = await client.get(_callback_url(user_id=telegram_user_id, ts=ts))

    assert response.status_code == 200
    assert response.text == "premium_ineligible"

    async with session_factory() as session:
        assert await _grants(session, user_id) == 0
        pending = await session.scalar(
            select(RewardSession).where(RewardSession.user_id == user_id)
        )
        assert pending is not None
        assert pending.status == REWARD_SESSION_PENDING

    async with _app_client(_settings(reward_premium_eligible=True), session_factory) as client:
        eligible = await client.get(_callback_url(user_id=telegram_user_id, ts=ts + 1))

    assert eligible.text == "accepted"
    async with session_factory() as session:
        assert await _grants(session, user_id) == 1
        redeemed = await session.scalar(
            select(RewardSession).where(RewardSession.user_id == user_id)
        )
        assert redeemed is not None
        assert redeemed.status == REWARD_SESSION_REDEEMED


async def test_blocked_user_is_rejected(
    session_factory: async_sessionmaker[AsyncSession], plans: None
) -> None:
    async with session_factory() as session:
        user = await _user(session, blocked=True)
        await session.commit()
        telegram_user_id = user.telegram_user_id
        user_id = user.id

    ts = int(datetime.now(UTC).timestamp())
    async with _app_client(_settings(), session_factory) as client:
        response = await client.get(_callback_url(user_id=telegram_user_id, ts=ts))

    assert response.text == "blocked"
    async with session_factory() as session:
        assert await _grants(session, user_id) == 0


async def test_reward_credit_is_reserved_and_consumed_before_refill(
    session_factory: async_sessionmaker[AsyncSession], plans: None
) -> None:
    now = datetime.now(UTC)
    async with session_factory() as session:
        user = await _user(session)
        entitlement = _entitlement(limit=0)
        await _open_session(session, user, now=now)
        granted = await grant_reward(
            session,
            telegram_user_id=user.telegram_user_id,
            block_id=BLOCK,
            event_at=now,
            now=now,
            settings=_settings(),
        )
        assert granted.status == "accepted"
        await session.commit()
        user_id = user.id
        assert await available_reward_credits(session, user_id, now=now) == 1

        first_job = await _job(session, user, "reward-reserve")
        reservation = await reserve_quota(
            session,
            user_id=user_id,
            download_job_id=first_job,
            entitlement=entitlement,
            now=now,
        )
        assert reservation.source == "reward_credit"
        assert reservation.reward_ledger_id is not None
        assert await available_reward_credits(session, user_id, now=now) == 0

        # A second download cannot take the same credit.
        second_job = await _job(session, user, "reward-second")

        with pytest.raises(AppError) as exc_info:
            await reserve_quota(
                session,
                user_id=user_id,
                download_job_id=second_job,
                entitlement=entitlement,
                now=now,
            )
        assert exc_info.value.code == ErrorCode.QUOTA_EXHAUSTED

        await commit_quota(session, first_job, now=now)
        assert await available_reward_credits(session, user_id, now=now) == 0
        await session.commit()


async def test_released_reservation_makes_the_credit_available_again(
    session_factory: async_sessionmaker[AsyncSession], plans: None
) -> None:
    now = datetime.now(UTC)
    async with session_factory() as session:
        user = await _user(session)
        entitlement = _entitlement(limit=0)
        await _open_session(session, user, now=now)
        await grant_reward(
            session,
            telegram_user_id=user.telegram_user_id,
            block_id=BLOCK,
            event_at=now,
            now=now,
            settings=_settings(),
        )
        await session.commit()

        job = await _job(session, user, "reward-release")
        reservation = await reserve_quota(
            session,
            user_id=user.id,
            download_job_id=job,
            entitlement=entitlement,
            now=now,
        )
        assert reservation.reward_ledger_id is not None

        await release_quota(session, job, now=now)
        assert await available_reward_credits(session, user.id, now=now) == 1
        await session.commit()


async def test_expired_credits_are_not_available(
    session_factory: async_sessionmaker[AsyncSession], plans: None
) -> None:
    now = datetime.now(UTC)
    past = now - timedelta(days=2)
    async with session_factory() as session:
        user = await _user(session)
        await _open_session(session, user, now=past)
        await grant_reward(
            session,
            telegram_user_id=user.telegram_user_id,
            block_id=BLOCK,
            event_at=past,
            now=past,
            settings=_settings(),
        )
        await session.commit()

        assert await available_reward_credits(session, user.id, now=now) == 0


async def test_forged_callback_without_a_session_grants_nothing(
    session_factory: async_sessionmaker[AsyncSession], plans: None
) -> None:
    async with session_factory() as session:
        user = await _user(session)
        await session.commit()
        telegram_user_id = user.telegram_user_id
        user_id = user.id

    ts = int(datetime.now(UTC).timestamp())
    async with _app_client(_settings(), session_factory) as client:
        response = await client.get(_callback_url(user_id=telegram_user_id, ts=ts))

    assert response.status_code == 200
    assert response.text == "no_session"
    async with session_factory() as session:
        assert await _grants(session, user_id) == 0
        event = await session.scalar(
            select(RewardEvent).where(RewardEvent.telegram_user_id == telegram_user_id)
        )
        assert event is not None
        assert event.status == "no_session"
        assert event.reason_code == "no_session"


async def test_replay_with_a_new_timestamp_finds_no_session(
    session_factory: async_sessionmaker[AsyncSession], plans: None
) -> None:
    now = datetime.now(UTC)
    async with session_factory() as session:
        user = await _user(session)
        await _open_session(session, user, now=now)
        await session.commit()
        telegram_user_id = user.telegram_user_id
        user_id = user.id

    ts = int(now.timestamp())
    async with _app_client(_settings(), session_factory) as client:
        first = await client.get(_callback_url(user_id=telegram_user_id, ts=ts))
        replay = await client.get(_callback_url(user_id=telegram_user_id, ts=ts + 5))

    assert first.text == "accepted"
    assert replay.status_code == 200
    assert replay.text == "no_session"
    async with session_factory() as session:
        assert await _grants(session, user_id) == 1
        statuses = (
            (
                await session.execute(
                    select(RewardEvent.status).where(
                        RewardEvent.telegram_user_id == telegram_user_id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert sorted(statuses) == ["accepted", "no_session"]


async def test_old_replay_does_not_consume_a_newer_session(
    session_factory: async_sessionmaker[AsyncSession], plans: None
) -> None:
    now = datetime.now(UTC)
    async with session_factory() as session:
        user = await _user(session)
        await _open_session(session, user, now=now)
        await session.commit()
        telegram_user_id = user.telegram_user_id
        user_id = user.id

    ts = int(now.timestamp())
    async with _app_client(_settings(), session_factory) as client:
        first = await client.get(_callback_url(user_id=telegram_user_id, ts=ts))
        assert first.text == "accepted"

        # The user starts a new ad before the old callback is replayed.
        async with session_factory() as session:
            user = await session.get(User, user_id)
            assert user is not None
            newer = await _open_session(session, user, now=now + timedelta(seconds=10))
            await session.commit()

        replay = await client.get(_callback_url(user_id=telegram_user_id, ts=ts + 5))

    assert replay.text == "no_session"
    async with session_factory() as session:
        assert await _grants(session, user_id) == 1
        newer_session = await session.scalar(
            select(RewardSession).where(RewardSession.id == newer.session_id)
        )
        assert newer_session is not None
        assert newer_session.status == REWARD_SESSION_PENDING


async def test_expired_session_never_redeems(
    session_factory: async_sessionmaker[AsyncSession], plans: None
) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    past = now - timedelta(seconds=1000)
    async with session_factory() as session:
        user = await _user(session)
        opened = await _open_session(session, user, now=past)
        await session.commit()
        telegram_user_id = user.telegram_user_id
        user_id = user.id

    async with _app_client(_settings(), session_factory) as client:
        response = await client.get(
            _callback_url(user_id=telegram_user_id, ts=int(now.timestamp()))
        )

    assert response.status_code == 200
    assert response.text == "no_session"
    async with session_factory() as session:
        assert await _grants(session, user_id) == 0
        reward_session = await session.scalar(
            select(RewardSession).where(RewardSession.id == opened.session_id)
        )
        assert reward_session is not None
        assert reward_session.status == REWARD_SESSION_EXPIRED


async def test_concurrent_callbacks_for_one_session_redeem_once(
    session_factory: async_sessionmaker[AsyncSession], plans: None
) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    async with session_factory() as session:
        user = await _user(session)
        await _open_session(session, user, now=now)
        await session.commit()
        telegram_user_id = user.telegram_user_id
        user_id = user.id

    ts = int(now.timestamp())
    async with _app_client(_settings(), session_factory) as client:
        responses = await asyncio.gather(
            client.get(_callback_url(user_id=telegram_user_id, ts=ts)),
            client.get(_callback_url(user_id=telegram_user_id, ts=ts + 5)),
        )

    assert sorted(response.text for response in responses) == ["accepted", "no_session"]
    async with session_factory() as session:
        assert await _grants(session, user_id) == 1
        reward_session = await session.scalar(
            select(RewardSession).where(RewardSession.user_id == user_id)
        )
        assert reward_session is not None
        assert reward_session.status == REWARD_SESSION_REDEEMED


async def test_new_ad_fetch_reuses_a_pending_session_then_replaces_an_expired_one(
    session_factory: async_sessionmaker[AsyncSession], plans: None
) -> None:
    now = datetime.now(UTC)
    async with session_factory() as session:
        user = await _user(session)
        first = await _open_session(session, user, now=now)
        second = await _open_session(session, user, now=now + timedelta(seconds=1))

        assert first.created is True
        assert second.created is False
        assert second.session_id == first.session_id

        third = await _open_session(session, user, now=now + timedelta(seconds=901))
        assert third.created is True
        assert third.session_id != first.session_id
        await session.commit()

        rows = (
            (await session.execute(select(RewardSession).where(RewardSession.user_id == user.id)))
            .scalars()
            .all()
        )
        statuses = {row.id: row.status for row in rows}
        assert statuses[first.session_id] == REWARD_SESSION_EXPIRED
        assert statuses[third.session_id] == REWARD_SESSION_PENDING


async def test_blocked_user_does_not_open_a_reward_session(
    session_factory: async_sessionmaker[AsyncSession], plans: None
) -> None:
    now = datetime.now(UTC)
    async with session_factory() as session:
        user = await _user(session, blocked=True)
        result = await open_reward_ad_session(
            session,
            user=user,
            block=BLOCK,
            now=now,
            settings=_settings(),
        )
        await session.commit()
        user_id = user.id

    assert result.status == "blocked"
    assert result.session_id is None
    async with session_factory() as session:
        rows = await session.scalar(
            select(func.count(RewardSession.id)).where(RewardSession.user_id == user_id)
        )
        assert rows == 0


async def test_premium_user_does_not_open_a_reward_session(
    session_factory: async_sessionmaker[AsyncSession], plans: None
) -> None:
    now = datetime.now(UTC)
    async with session_factory() as session:
        user = await _premium_user(session)
        result = await open_reward_ad_session(
            session,
            user=user,
            block=BLOCK,
            now=now,
            settings=_settings(),
        )
        await session.commit()
        user_id = user.id

    assert result.status == "premium_ineligible"
    assert result.session_id is None
    async with session_factory() as session:
        rows = await session.scalar(
            select(func.count(RewardSession.id)).where(RewardSession.user_id == user_id)
        )
        assert rows == 0


async def test_capped_user_does_not_open_another_reward_session(
    session_factory: async_sessionmaker[AsyncSession], plans: None
) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    settings = _settings(reward_daily_cap=1)
    async with session_factory() as session:
        user = await _user(session)
        await _open_session(session, user, now=now, settings=settings)
        granted = await grant_reward(
            session,
            telegram_user_id=user.telegram_user_id,
            block_id=BLOCK,
            event_at=now,
            now=now,
            settings=settings,
        )
        assert granted.status == "accepted"
        await session.commit()
        user_id = user.id

        result = await open_reward_ad_session(
            session,
            user=user,
            block=BLOCK,
            now=now,
            settings=settings,
        )
        await session.commit()

    assert result.status == "capped"
    assert result.session_id is None
    assert result.cap_resets_at == next_quota_period_start(now)
    async with session_factory() as session:
        pending = await session.scalar(
            select(func.count(RewardSession.id)).where(
                RewardSession.user_id == user_id,
                RewardSession.status == REWARD_SESSION_PENDING,
            )
        )
        total = await session.scalar(
            select(func.count(RewardSession.id)).where(RewardSession.user_id == user_id)
        )
        assert pending == 0
        assert total == 1


async def test_expiry_cleanup_marks_stale_sessions_expired(
    session_factory: async_sessionmaker[AsyncSession], plans: None
) -> None:
    now = datetime.now(UTC)
    async with session_factory() as session:
        user = await _user(session)
        opened = await _open_session(session, user, now=now - timedelta(seconds=1000))
        await session.commit()

        expired = await expire_stale_reward_sessions(session, now=now)
        await session.commit()

        assert expired == 1
        reward_session = await session.scalar(
            select(RewardSession).where(RewardSession.id == opened.session_id)
        )
        assert reward_session is not None
        assert reward_session.status == REWARD_SESSION_EXPIRED

        # Re-running the cleanup is harmless.
        assert await expire_stale_reward_sessions(session, now=now) == 0


async def test_concurrent_same_event_grants_exactly_once(
    session_factory: async_sessionmaker[AsyncSession], plans: None
) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    async with session_factory() as session:
        user = await _user(session)
        await _open_session(session, user, now=now)
        await session.commit()
        telegram_user_id = user.telegram_user_id
        user_id = user.id

    settings = _settings()
    results = await asyncio.gather(
        *[
            _grant_status(
                session_factory,
                user_id=user_id,
                telegram_user_id=telegram_user_id,
                event_at=now,
                now=now,
                settings=settings,
                open_session=False,
            )
            for _ in range(4)
        ]
    )

    assert results.count("accepted") == 1
    assert results.count("duplicate") == 3
    async with session_factory() as session:
        assert await _grants(session, user_id) == 1


async def test_concurrent_distinct_events_stop_at_the_daily_cap(
    session_factory: async_sessionmaker[AsyncSession], plans: None
) -> None:
    cap = 3
    settings = _settings(reward_daily_cap=cap)
    now = datetime.now(UTC).replace(microsecond=0)
    first_event = now - timedelta(seconds=60)
    blocks = [f"6000{index}" for index in range(8)]

    async with session_factory() as session:
        user = await _user(session)
        for block in blocks:
            await _open_session(
                session,
                user,
                now=first_event,
                block=block,
                settings=settings,
            )
        await session.commit()
        telegram_user_id = user.telegram_user_id
        user_id = user.id

    results = await asyncio.gather(
        *[
            _grant_status(
                session_factory,
                user_id=user_id,
                telegram_user_id=telegram_user_id,
                event_at=first_event + timedelta(seconds=offset),
                now=now,
                settings=settings,
                block=block,
                open_session=False,
            )
            for offset, block in enumerate(blocks)
        ]
    )

    assert results.count("accepted") == cap
    assert results.count("capped") == len(blocks) - cap
    async with session_factory() as session:
        assert await _grants(session, user_id) == cap


async def test_commit_and_release_cannot_both_settle_a_reward_reservation(
    session_factory: async_sessionmaker[AsyncSession], plans: None
) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    async with session_factory() as session:
        user = await _user(session)
        await _open_session(session, user, now=now)
        await grant_reward(
            session,
            telegram_user_id=user.telegram_user_id,
            block_id=BLOCK,
            event_at=now,
            now=now,
            settings=_settings(),
        )
        job_id = await _job(session, user, "concurrent-settlement")
        reservation = await reserve_quota(
            session,
            user_id=user.id,
            download_job_id=job_id,
            entitlement=_entitlement(limit=0),
            now=now,
        )
        assert reservation.reward_ledger_id is not None
        await session.commit()
        user_id = user.id

    async def _commit() -> str | None:
        async with session_factory() as session:
            settled = await commit_quota(session, job_id, now=now)
            await session.commit()
            return settled.status if settled is not None else None

    async def _release() -> str | None:
        async with session_factory() as session:
            settled = await release_quota(session, job_id, now=now)
            await session.commit()
            return settled.status if settled is not None else None

    commit_status, release_status = await asyncio.gather(_commit(), _release())

    # Both calls observe the winner's terminal state; they cannot produce one
    # committed and one released outcome.
    assert commit_status == release_status
    assert commit_status in {"committed", "released"}

    async with session_factory() as session:
        settlement_rows = int(
            await session.scalar(
                select(func.count(UsageLedger.id)).where(
                    UsageLedger.download_job_id == job_id,
                    UsageLedger.entry_type.in_(("download_committed", "reservation_released")),
                )
            )
            or 0
        )
        assert settlement_rows == 1
        available = await available_reward_credits(session, user_id, now=now)
        assert available == (1 if commit_status == "released" else 0)


async def test_daily_cap_resets_at_lagos_midnight_not_utc_midnight(
    session_factory: async_sessionmaker[AsyncSession], plans: None
) -> None:
    async with session_factory() as session:
        user = await _user(session)
        await session.commit()
        telegram_user_id = user.telegram_user_id
        user_id = user.id

    settings = _settings(reward_daily_cap=1)
    # Lagos is UTC+01:00 year-round: local midnight is 23:00Z the day before.
    before_midnight = datetime(2026, 11, 17, 22, 0, tzinfo=UTC)
    just_before_midnight = datetime(2026, 11, 17, 22, 59, 59, tzinfo=UTC)
    at_midnight = datetime(2026, 11, 17, 23, 0, tzinfo=UTC)

    first = await _grant_status(
        session_factory,
        user_id=user_id,
        telegram_user_id=telegram_user_id,
        event_at=before_midnight,
        now=before_midnight,
        settings=settings,
    )
    same_lagos_day = await _grant_status(
        session_factory,
        user_id=user_id,
        telegram_user_id=telegram_user_id,
        event_at=just_before_midnight,
        now=just_before_midnight,
        settings=settings,
    )
    next_lagos_day = await _grant_status(
        session_factory,
        user_id=user_id,
        telegram_user_id=telegram_user_id,
        event_at=at_midnight,
        now=at_midnight,
        settings=settings,
    )

    assert first == "accepted"
    assert same_lagos_day == "capped"
    assert next_lagos_day == "accepted"
    async with session_factory() as session:
        assert await _grants(session, user_id) == 2


async def test_daily_cap_does_not_reset_at_utc_midnight(
    session_factory: async_sessionmaker[AsyncSession], plans: None
) -> None:
    async with session_factory() as session:
        user = await _user(session)
        await session.commit()
        telegram_user_id = user.telegram_user_id

    settings = _settings(reward_daily_cap=1)
    # Both instants fall inside the Lagos day that started at 23:00Z on the 17th.
    before_utc_midnight = datetime(2026, 11, 17, 23, 30, tzinfo=UTC)
    after_utc_midnight = datetime(2026, 11, 18, 0, 30, tzinfo=UTC)

    first = await _grant_status(
        session_factory,
        user_id=user.id,
        telegram_user_id=telegram_user_id,
        event_at=before_utc_midnight,
        now=before_utc_midnight,
        settings=settings,
    )
    second = await _grant_status(
        session_factory,
        user_id=user.id,
        telegram_user_id=telegram_user_id,
        event_at=after_utc_midnight,
        now=after_utc_midnight,
        settings=settings,
    )

    assert first == "accepted"
    assert second == "capped"


async def test_expired_credit_cannot_be_reserved(
    session_factory: async_sessionmaker[AsyncSession], plans: None
) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    past = now - timedelta(days=2)

    async with session_factory() as session:
        user = await _user(session)
        await _open_session(session, user, now=past)
        await grant_reward(
            session,
            telegram_user_id=user.telegram_user_id,
            block_id=BLOCK,
            event_at=past,
            now=past,
            settings=_settings(),
        )
        await session.commit()
        assert await available_reward_credits(session, user.id, now=now) == 0

        job_id = await _job(session, user, "expired-credit")
        with pytest.raises(AppError) as exc_info:
            await reserve_quota(
                session,
                user_id=user.id,
                download_job_id=job_id,
                entitlement=_entitlement(limit=0),
                now=now,
            )

    assert exc_info.value.code == ErrorCode.QUOTA_EXHAUSTED


async def test_prefixed_block_and_numeric_block_are_the_same_event(
    session_factory: async_sessionmaker[AsyncSession], plans: None
) -> None:
    now = datetime.now(UTC)
    async with session_factory() as session:
        user = await _user(session)
        await _open_session(session, user, now=now)
        await session.commit()
        telegram_user_id = user.telegram_user_id
        user_id = user.id

    ts = int(now.timestamp())
    async with _app_client(_settings(), session_factory) as client:
        first = await client.get(_callback_url(user_id=telegram_user_id, ts=ts))
        second = await client.get(_callback_url(user_id=telegram_user_id, ts=ts, block="bot-50001"))

    assert first.text == "accepted"
    assert second.text == "duplicate"
    async with session_factory() as session:
        assert await _grants(session, user_id) == 1


async def test_released_credit_still_counts_towards_the_daily_cap(
    session_factory: async_sessionmaker[AsyncSession], plans: None
) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    settings = _settings(reward_daily_cap=1)

    async with session_factory() as session:
        user = await _user(session)
        await _open_session(session, user, now=now, settings=settings)
        granted = await grant_reward(
            session,
            telegram_user_id=user.telegram_user_id,
            block_id=BLOCK,
            event_at=now,
            now=now,
            settings=settings,
        )
        assert granted.status == "accepted"
        await session.commit()

        job_id = await _job(session, user, "released-cap")
        reservation = await reserve_quota(
            session,
            user_id=user.id,
            download_job_id=job_id,
            entitlement=_entitlement(limit=0),
            now=now,
        )
        assert reservation.reward_ledger_id is not None
        await release_quota(session, job_id, now=now)
        await session.commit()
        assert await available_reward_credits(session, user.id, now=now) == 1

        # A new ad view creates the next session; the cap still rejects it.
        await _open_session(session, user, now=now + timedelta(seconds=1), settings=settings)
        replay = await grant_reward(
            session,
            telegram_user_id=user.telegram_user_id,
            block_id=BLOCK,
            event_at=now + timedelta(seconds=1),
            now=now + timedelta(seconds=1),
            settings=settings,
        )
        await session.commit()
        assert replay.status == "capped"
        assert await _grants(session, user.id) == 1
