import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.models import MediaCache
from backend.storage.cache import cache_file_exists


async def find_ready_cache(
    session: AsyncSession,
    *,
    media_key: str,
    media_root: Path,
    now: datetime | None = None,
) -> MediaCache | None:
    now = now or datetime.now(UTC)
    entry = await session.scalar(
        select(MediaCache).where(
            MediaCache.media_key == media_key,
            MediaCache.status == "ready",
            MediaCache.expires_at > now,
        )
    )
    if entry is None:
        return None
    if not cache_file_exists(entry.storage_path, media_root):
        await session.execute(
            update(MediaCache).where(MediaCache.id == entry.id).values(status="invalid")
        )
        return None
    entry.last_accessed_at = now
    return entry


async def upsert_cache_entry(
    session: AsyncSession,
    *,
    media_key: str,
    platform: str,
    source_identity_hash: str,
    output_profile: str,
    processing_version: str,
    storage_path: str,
    file_size_bytes: int,
    mime_type: str,
    telegram_file_id: str | None,
    retention_hours: int,
    now: datetime | None = None,
) -> uuid.UUID:
    now = now or datetime.now(UTC)
    expires_at = now + timedelta(hours=min(retention_hours, 24))
    entry_id = uuid.uuid4()
    stmt = (
        pg_insert(MediaCache)
        .values(
            id=entry_id,
            media_key=media_key,
            platform=platform,
            source_identity_hash=source_identity_hash,
            output_profile=output_profile,
            processing_version=processing_version,
            storage_path=storage_path,
            file_size_bytes=file_size_bytes,
            mime_type=mime_type,
            telegram_file_id=telegram_file_id,
            created_at=now,
            expires_at=expires_at,
            last_accessed_at=now,
            status="ready",
        )
        .on_conflict_do_update(
            index_elements=[MediaCache.media_key],
            set_={
                "storage_path": storage_path,
                "file_size_bytes": file_size_bytes,
                "mime_type": mime_type,
                "telegram_file_id": telegram_file_id,
                "created_at": now,
                "expires_at": expires_at,
                "last_accessed_at": now,
                "status": "ready",
            },
        )
        .returning(MediaCache.id)
    )
    returned_id = await session.scalar(stmt)
    if returned_id is None:
        raise RuntimeError("Media cache upsert did not return a row")
    return returned_id
