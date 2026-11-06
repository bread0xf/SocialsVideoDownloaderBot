import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.models import User


@dataclass(frozen=True, slots=True)
class TelegramIdentity:
    telegram_user_id: int
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    language_code: str | None = None


async def upsert_telegram_user(
    session: AsyncSession,
    identity: TelegramIdentity,
    *,
    now: datetime | None = None,
) -> User:
    now = now or datetime.now(UTC)
    user_id = uuid.uuid4()
    stmt = (
        pg_insert(User)
        .values(
            id=user_id,
            telegram_user_id=identity.telegram_user_id,
            username=identity.username,
            first_name=identity.first_name,
            last_name=identity.last_name,
            language_code=identity.language_code,
            created_at=now,
            updated_at=now,
            last_seen_at=now,
        )
        .on_conflict_do_update(
            index_elements=[User.telegram_user_id],
            set_={
                "username": identity.username,
                "first_name": identity.first_name,
                "last_name": identity.last_name,
                "language_code": identity.language_code,
                "updated_at": now,
                "last_seen_at": now,
            },
        )
        .returning(User.id)
    )
    returned_id = await session.scalar(stmt)
    if returned_id is None:
        raise RuntimeError("Telegram user upsert did not return a row")
    user = await session.scalar(select(User).where(User.id == returned_id))
    if user is None:
        raise RuntimeError("Telegram user disappeared after upsert")
    return user
