import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import Settings, get_settings
from backend.core.errors import AppError, ErrorCode
from backend.database.models import Plan, Subscription

_ACCESS_STATUSES = ("active", "cancelled")


@dataclass(frozen=True, slots=True)
class Entitlement:
    plan_code: str
    max_resolution_p: int
    daily_included_limit: int | None
    quota_source: str
    priority: int
    sponsor_eligible: bool
    evaluated_at: datetime
    subscription_id: uuid.UUID | None
    paid_through: datetime | None

    @property
    def is_premium(self) -> bool:
        return self.plan_code == "premium"

    @property
    def output_profile(self) -> str:
        return f"{self.plan_code}-{self.max_resolution_p}p"


async def resolve_entitlement(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    now: datetime | None = None,
    settings: Settings | None = None,
) -> Entitlement:
    settings = settings or get_settings()
    now = now or datetime.now(UTC)

    subscription_stmt = (
        select(Subscription, Plan)
        .join(Plan, Subscription.plan_id == Plan.id)
        .where(
            Subscription.user_id == user_id,
            Subscription.status.in_(_ACCESS_STATUSES),
            Subscription.paid_through.is_not(None),
            Subscription.paid_through >= now,
            Plan.is_active.is_(True),
        )
        .order_by(Subscription.paid_through.desc())
        .limit(1)
    )
    row = (await session.execute(subscription_stmt)).first()
    if row is not None:
        subscription, plan = row
        configured_limit = plan.daily_included_downloads
        if configured_limit is None:
            configured_limit = settings.premium_daily_limit
        return Entitlement(
            plan_code=plan.code,
            max_resolution_p=min(plan.max_resolution_p, settings.premium_max_resolution_p),
            daily_included_limit=configured_limit,
            quota_source="premium_included",
            priority=plan.priority,
            sponsor_eligible=False,
            evaluated_at=now,
            subscription_id=subscription.id,
            paid_through=subscription.paid_through,
        )

    free_plan = await session.scalar(
        select(Plan).where(Plan.code == "free", Plan.is_active.is_(True))
    )
    if free_plan is None:
        raise AppError(ErrorCode.INTERNAL_ERROR, "The service is temporarily unavailable.")

    free_limit = free_plan.daily_included_downloads or settings.free_daily_limit
    return Entitlement(
        plan_code=free_plan.code,
        max_resolution_p=min(free_plan.max_resolution_p, settings.free_max_resolution_p),
        daily_included_limit=free_limit,
        quota_source="included",
        priority=free_plan.priority,
        sponsor_eligible=True,
        evaluated_at=now,
        subscription_id=None,
        paid_through=None,
    )
