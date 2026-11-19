import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


async def lock_user_quota(session: AsyncSession, user_id: uuid.UUID) -> None:
    """Serialize quota decisions for one user inside the current transaction."""
    await session.execute(
        select(func.pg_advisory_xact_lock(func.hashtextextended(str(user_id), 0)))
    )
