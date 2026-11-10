import asyncio
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import structlog
from arq.connections import ArqRedis
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.core.config import Settings, get_settings
from backend.core.errors import AppError, ErrorCode
from backend.database.models import DownloadJob, MediaCache, OutboxEvent, User
from backend.delivery.presentation import build_caption, build_filename
from backend.delivery.telegram import BotDelivery, DeliveredMedia, Delivery, TelegramDeliveryError
from backend.downloads.cache_keys import build_media_key, source_identity_hash
from backend.downloads.outbox import EVENT_DOWNLOAD_REQUESTED, enqueue_download_requested
from backend.downloads.state import ACTIVE_STATUSES, TERMINAL_STATUSES, JobStatus, transition
from backend.entitlements.service import Entitlement, resolve_entitlement
from backend.media.cache import find_ready_cache, upsert_cache_entry
from backend.media.ffprobe import probe_media, validate_probe
from backend.media.processing import PreparedMedia, prepare_media
from backend.media.selection import select_format
from backend.platforms.adapters.base import PlatformAdapter
from backend.platforms.adapters.ytdlp import YtDlpAdapter
from backend.platforms.registry import platform_registry
from backend.platforms.urls import NormalizedURL, normalize_url, resolve_public_addresses
from backend.storage.cache import remove_cache_file, store_cache_file
from backend.storage.workspace import cleanup_stale_workspaces, job_workspace
from backend.usage.service import commit_quota, release_quota

logger = structlog.get_logger(__name__)

_RETRYABLE_ERRORS = frozenset(
    {
        ErrorCode.TEMPORARY_FAILURE,
        ErrorCode.PROCESSING_TIMEOUT,
        ErrorCode.SOURCE_UNAVAILABLE,
        ErrorCode.TELEGRAM_DELIVERY_FAILED,
    }
)


@dataclass(frozen=True, slots=True)
class JobSnapshot:
    job_id: uuid.UUID
    user_id: uuid.UUID
    telegram_user_id: int
    source_url: str
    media_key: str | None
    attempt_count: int


def _settings(ctx: dict[str, Any]) -> Settings:
    return cast(Settings, ctx["settings"])


def _factory(ctx: dict[str, Any]) -> async_sessionmaker[AsyncSession]:
    return cast(async_sessionmaker[AsyncSession], ctx["session_factory"])


def _adapter(ctx: dict[str, Any]) -> PlatformAdapter:
    return cast(PlatformAdapter, ctx["adapter"])


def _redis(ctx: dict[str, Any]) -> ArqRedis | None:
    redis = ctx.get("redis")
    return cast(ArqRedis, redis) if redis is not None else None


def _effective_max_bytes(settings: Settings) -> int:
    return min(settings.max_media_bytes, settings.telegram_upload_max_bytes)


def _backoff_seconds(attempt_count: int) -> int:
    return min(300, 5 * (2 ** max(0, attempt_count - 1)))


async def _claim_job(ctx: dict[str, Any], raw_job_id: str) -> JobSnapshot | None:
    try:
        job_id = uuid.UUID(raw_job_id)
    except ValueError:
        logger.warning("download_task_invalid_job_id")
        return None

    settings = _settings(ctx)
    now = datetime.now(UTC)
    async with _factory(ctx)() as session:
        row = (
            await session.execute(
                select(DownloadJob, User)
                .join(User, DownloadJob.user_id == User.id)
                .where(DownloadJob.id == job_id)
                .with_for_update(of=DownloadJob, skip_locked=True)
            )
        ).first()
        if row is None:
            return None
        job, user = row
        if job.status != JobStatus.QUEUED.value:
            return None
        if job.attempt_count >= settings.download_max_attempts:
            job.status = JobStatus.FAILED.value
            job.stage = JobStatus.FAILED.value
            job.failed_at = now
            job.error_code = ErrorCode.TEMPORARY_FAILURE.value
            job.error_detail_safe = "The download could not be completed after several attempts."
            await release_quota(session, job.id, now=now)
            await session.commit()
            return None

        job.status = JobStatus.EXTRACTING.value
        job.stage = JobStatus.EXTRACTING.value
        job.started_at = now
        job.attempt_count += 1
        job.error_code = None
        job.error_detail_safe = None
        snapshot = JobSnapshot(
            job_id=job.id,
            user_id=user.id,
            telegram_user_id=user.telegram_user_id,
            source_url=job.canonical_url or job.submitted_url,
            media_key=job.media_key,
            attempt_count=job.attempt_count,
        )
        await session.commit()
    return snapshot


async def _set_status(ctx: dict[str, Any], job_id: uuid.UUID, new_status: JobStatus) -> None:
    async with _factory(ctx)() as session:
        job = await session.scalar(
            select(DownloadJob).where(DownloadJob.id == job_id).with_for_update()
        )
        if job is None:
            raise AppError(ErrorCode.INTERNAL_ERROR, "The download job no longer exists.")
        job.status = transition(job.status, new_status.value).value
        job.stage = new_status.value
        await session.commit()


async def _resolve_entitlement(ctx: dict[str, Any], snapshot: JobSnapshot) -> Entitlement:
    async with _factory(ctx)() as session:
        entitlement = await resolve_entitlement(
            session,
            snapshot.user_id,
            settings=_settings(ctx),
        )
        await session.commit()
        return entitlement


async def _lookup_cache(
    ctx: dict[str, Any], media_key: str
) -> tuple[uuid.UUID, str, str | None, str | None, str | None] | None:
    settings = _settings(ctx)
    async with _factory(ctx)() as session:
        entry = await find_ready_cache(
            session,
            media_key=media_key,
            media_root=settings.media_root,
        )
        await session.commit()
        if entry is None:
            return None
        return (
            entry.id,
            entry.storage_path,
            entry.telegram_file_id,
            entry.title,
            entry.uploader,
        )


async def _invalidate_cache(ctx: dict[str, Any], cache_entry_id: uuid.UUID) -> None:
    async with _factory(ctx)() as session:
        await session.execute(
            update(MediaCache).where(MediaCache.id == cache_entry_id).values(status="invalid")
        )
        await session.commit()


async def _deliver(
    ctx: dict[str, Any],
    snapshot: JobSnapshot,
    media: PreparedMedia,
    *,
    caption: str | None = None,
    filename: str | None = None,
) -> DeliveredMedia:
    delivery = cast(Delivery | None, ctx.get("delivery"))
    if delivery is None:
        raise AppError(
            ErrorCode.INTERNAL_ERROR,
            "Telegram delivery is not configured.",
        )
    try:
        return await delivery.send_video(
            snapshot.telegram_user_id,
            media,
            caption=caption,
            parse_mode="HTML" if caption else None,
            filename=filename,
        )
    except TelegramDeliveryError as exc:
        raise AppError(
            ErrorCode.TELEGRAM_DELIVERY_FAILED,
            "The video could not be delivered to Telegram. Please try again later.",
        ) from exc


async def _finalize_delivered(
    ctx: dict[str, Any],
    *,
    snapshot: JobSnapshot,
    normalized_url: NormalizedURL,
    entitlement: Entitlement,
    media: PreparedMedia,
    media_key: str,
    delivered: DeliveredMedia,
    cache_entry_id: uuid.UUID | None,
    stored_cache_path: Path | None,
    title: str | None = None,
    uploader: str | None = None,
) -> bool:
    settings = _settings(ctx)
    for attempt in range(3):
        try:
            now = datetime.now(UTC)
            async with _factory(ctx)() as session:
                job = await session.scalar(
                    select(DownloadJob).where(DownloadJob.id == snapshot.job_id).with_for_update()
                )
                if job is None:
                    return False
                if job.status == JobStatus.COMPLETED.value:
                    return True
                if job.status in TERMINAL_STATUSES:
                    return False
                job.status = transition(job.status, JobStatus.COMPLETED.value).value
                job.stage = JobStatus.COMPLETED.value
                job.completed_at = now
                job.selected_resolution_p = media.probe.quality_height
                job.output_bytes = media.probe.size_bytes
                job.media_key = media_key

                final_cache_id: uuid.UUID | None = None
                if cache_entry_id is not None:
                    entry = await session.scalar(
                        select(MediaCache).where(MediaCache.id == cache_entry_id)
                    )
                    if entry is not None:
                        entry.last_accessed_at = now
                        if delivered.file_id is not None:
                            entry.telegram_file_id = delivered.file_id
                        final_cache_id = entry.id
                elif stored_cache_path is not None:
                    final_cache_id = await upsert_cache_entry(
                        session,
                        media_key=media_key,
                        platform=normalized_url.platform,
                        source_identity_hash=source_identity_hash(normalized_url.url),
                        output_profile=entitlement.output_profile,
                        processing_version=settings.processing_version,
                        storage_path=str(stored_cache_path),
                        file_size_bytes=media.probe.size_bytes,
                        mime_type=media.mime_type,
                        telegram_file_id=delivered.file_id,
                        retention_hours=settings.media_retention_hours,
                        title=title,
                        uploader=uploader,
                        now=now,
                    )
                job.cache_entry_id = final_cache_id
                await commit_quota(session, job.id, now=now)
                await session.commit()
                return True
        except Exception:
            logger.exception("download_finalize_failed", job_id=str(snapshot.job_id))
            if attempt < 2:
                await asyncio.sleep(0.5 * (attempt + 1))
    return False


async def _handle_failure(
    ctx: dict[str, Any],
    snapshot: JobSnapshot,
    error: AppError,
    *,
    started: float | None = None,
) -> str:
    settings = _settings(ctx)
    now = datetime.now(UTC)
    retryable = error.code in _RETRYABLE_ERRORS
    retry_scheduled = False

    async with _factory(ctx)() as session:
        job = await session.scalar(
            select(DownloadJob).where(DownloadJob.id == snapshot.job_id).with_for_update()
        )
        if job is None or job.status in TERMINAL_STATUSES:
            return "skipped"

        if retryable and job.attempt_count < settings.download_max_attempts:
            job.status = transition(job.status, JobStatus.QUEUED.value).value
            job.stage = JobStatus.QUEUED.value
            job.started_at = None
            job.error_code = error.code.value
            job.error_detail_safe = error.safe_message
            enqueue_download_requested(
                session,
                job.id,
                now=now,
                available_at=now + timedelta(seconds=_backoff_seconds(job.attempt_count)),
            )
            retry_scheduled = True
        else:
            job.status = transition(job.status, JobStatus.FAILED.value).value
            job.stage = JobStatus.FAILED.value
            job.failed_at = now
            job.error_code = error.code.value
            job.error_detail_safe = error.safe_message
            await release_quota(session, job.id, now=now)
        await session.commit()

    elapsed_ms = _elapsed_ms(started)

    if retry_scheduled:
        logger.info(
            "download_retry_scheduled",
            job_id=str(snapshot.job_id),
            error_code=error.code.value,
            attempt=snapshot.attempt_count,
            elapsed_ms=elapsed_ms,
        )
        return "retry"

    logger.info(
        "download_failed",
        job_id=str(snapshot.job_id),
        error_code=error.code.value,
        elapsed_ms=elapsed_ms,
    )
    delivery = cast(Delivery | None, ctx.get("delivery"))
    if delivery is not None:
        await delivery.send_text(
            snapshot.telegram_user_id,
            f"Sorry, this download failed. {error.safe_message}",
        )
    return "failed"


def _elapsed_ms(started: float | None) -> int | None:
    if started is None:
        return None
    return int((time.monotonic() - started) * 1000)


def _log_completed(
    snapshot: JobSnapshot,
    *,
    started: float,
    cache_hit: bool,
    media: PreparedMedia,
    platform: str,
    outcome: str,
) -> None:
    logger.info(
        "download_completed",
        job_id=str(snapshot.job_id),
        attempt=snapshot.attempt_count,
        cache_hit=cache_hit,
        elapsed_ms=_elapsed_ms(started),
        output_bytes=media.probe.size_bytes,
        resolution_p=media.probe.quality_height,
        platform=platform,
        outcome=outcome,
    )


async def process_download(ctx: dict[str, Any], job_id: str) -> str:
    settings = _settings(ctx)
    snapshot = await _claim_job(ctx, job_id)
    if snapshot is None:
        return "skipped"

    started = time.monotonic()
    logger.info(
        "download_started",
        job_id=str(snapshot.job_id),
        attempt=snapshot.attempt_count,
    )
    try:
        normalized_url = normalize_url(snapshot.source_url)
        platform_registry.require_accepting(normalized_url.platform, normalized_url.content_type)
        entitlement = await _resolve_entitlement(ctx, snapshot)
        media_key = build_media_key(
            platform=normalized_url.platform,
            source_id=normalized_url.source_id,
            output_profile=entitlement.output_profile,
            processing_version=settings.processing_version,
        )
        max_bytes = _effective_max_bytes(settings)
        max_height = entitlement.max_resolution_p

        cached = await _lookup_cache(ctx, media_key)
        if cached is not None:
            cache_entry_id, storage_path, _, cached_title, cached_uploader = cached
            try:
                cached_probe = await probe_media(Path(storage_path))
                validate_probe(
                    cached_probe,
                    max_height=max_height,
                    max_bytes=max_bytes,
                    max_duration_seconds=settings.max_media_duration_seconds,
                )
            except AppError:
                await _invalidate_cache(ctx, cache_entry_id)
            else:
                media = PreparedMedia(
                    path=Path(storage_path),
                    probe=cached_probe,
                    mime_type="video/mp4",
                )
                await _set_status(ctx, snapshot.job_id, JobStatus.SELECTING_FORMAT)
                await _set_status(ctx, snapshot.job_id, JobStatus.PROCESSING)
                await _set_status(ctx, snapshot.job_id, JobStatus.DELIVERING)
                delivered = await _deliver(
                    ctx,
                    snapshot,
                    media,
                    caption=build_caption(
                        platform=normalized_url.platform,
                        title=cached_title,
                        uploader=cached_uploader,
                        height=cached_probe.quality_height,
                    ),
                    filename=build_filename(
                        normalized_url.platform,
                        normalized_url.source_id,
                    ),
                )
                finalized = await _finalize_delivered(
                    ctx,
                    snapshot=snapshot,
                    normalized_url=normalized_url,
                    entitlement=entitlement,
                    media=media,
                    media_key=media_key,
                    delivered=delivered,
                    cache_entry_id=cache_entry_id,
                    stored_cache_path=None,
                )
                outcome = "completed" if finalized else "completed_unfinalized"
                _log_completed(
                    snapshot,
                    started=started,
                    cache_hit=True,
                    media=media,
                    platform=normalized_url.platform,
                    outcome=outcome,
                )
                return outcome

        with job_workspace(settings.media_root, snapshot.job_id) as workspace:
            await resolve_public_addresses(normalized_url.host)
            metadata = await _adapter(ctx).inspect(normalized_url, workspace.path)
            if metadata.is_live:
                raise AppError(ErrorCode.UNSUPPORTED_CONTENT, "Live streams are not supported.")
            if (
                metadata.duration_seconds is not None
                and metadata.duration_seconds > settings.max_media_duration_seconds
            ):
                raise AppError(
                    ErrorCode.DURATION_LIMIT,
                    "This video is longer than the supported limit.",
                )

            selection = select_format(
                metadata.formats,
                max_height=max_height,
                max_bytes=max_bytes,
                duration_seconds=metadata.duration_seconds,
            )
            await _set_status(ctx, snapshot.job_id, JobStatus.SELECTING_FORMAT)
            source_path = await _adapter(ctx).download(
                normalized_url,
                selection,
                workspace.path,
                max_bytes=max_bytes,
            )
            await _set_status(ctx, snapshot.job_id, JobStatus.PROCESSING)
            media = await prepare_media(
                source_path,
                workspace.path,
                max_height=max_height,
                max_bytes=max_bytes,
                max_duration_seconds=settings.max_media_duration_seconds,
                ffmpeg_timeout_seconds=settings.ffmpeg_timeout_seconds,
            )
            await _set_status(ctx, snapshot.job_id, JobStatus.DELIVERING)
            delivered = await _deliver(
                ctx,
                snapshot,
                media,
                caption=build_caption(
                    platform=normalized_url.platform,
                    title=metadata.title,
                    uploader=metadata.uploader,
                    height=media.probe.quality_height,
                ),
                filename=build_filename(
                    normalized_url.platform,
                    normalized_url.source_id,
                ),
            )

            stored_cache_path: Path | None = None
            try:
                stored_cache_path = await store_cache_file(
                    media.path,
                    settings.media_root,
                    media_key,
                )
            except Exception:
                logger.exception("download_cache_store_failed", job_id=str(snapshot.job_id))

            finalized = await _finalize_delivered(
                ctx,
                snapshot=snapshot,
                normalized_url=normalized_url,
                entitlement=entitlement,
                media=media,
                media_key=media_key,
                delivered=delivered,
                cache_entry_id=None,
                stored_cache_path=stored_cache_path,
                title=metadata.title,
                uploader=metadata.uploader,
            )
            outcome = "completed" if finalized else "completed_unfinalized"
            _log_completed(
                snapshot,
                started=started,
                cache_hit=False,
                media=media,
                platform=normalized_url.platform,
                outcome=outcome,
            )
            return outcome
    except AppError as exc:
        return await _handle_failure(ctx, snapshot, exc, started=started)
    except Exception:
        logger.exception("download_unexpected_failure", job_id=str(snapshot.job_id))
        return await _handle_failure(
            ctx,
            snapshot,
            AppError(
                ErrorCode.INTERNAL_ERROR,
                "The download could not be completed. Please try again later.",
            ),
            started=started,
        )


async def dispatch_outbox(ctx: dict[str, Any]) -> int:
    settings = _settings(ctx)
    redis = _redis(ctx)
    if redis is None:
        return 0

    now = datetime.now(UTC)
    published = 0
    async with _factory(ctx)() as session:
        events = (
            await session.scalars(
                select(OutboxEvent)
                .where(
                    OutboxEvent.published_at.is_(None),
                    OutboxEvent.available_at <= now,
                )
                .order_by(OutboxEvent.available_at)
                .limit(50)
                .with_for_update(skip_locked=True)
            )
        ).all()

        for event in events:
            if event.event_type != EVENT_DOWNLOAD_REQUESTED:
                event.published_at = now
                continue
            payload = event.payload if isinstance(event.payload, dict) else {}
            job_id = payload.get("job_id")
            if not isinstance(job_id, str):
                event.published_at = now
                continue
            try:
                await redis.enqueue_job(
                    "process_download",
                    job_id,
                    _job_id=f"outbox:{event.id}",
                )
            except Exception:
                event.attempt_count += 1
                event.last_error_code = "ENQUEUE_FAILED"
                if event.attempt_count >= settings.outbox_max_attempts:
                    event.published_at = now
                else:
                    event.available_at = now + timedelta(seconds=min(300, 2**event.attempt_count))
                logger.exception("outbox_enqueue_failed", event_id=str(event.id))
                continue
            event.published_at = now
            published += 1
        await session.commit()
    if published:
        logger.info("outbox_dispatched", count=published)
    return published


async def cleanup_cache(ctx: dict[str, Any]) -> int:
    settings = _settings(ctx)
    media_root = settings.media_root
    now = datetime.now(UTC)
    removed = 0

    for _ in range(20):
        async with _factory(ctx)() as session:
            entries = (
                await session.scalars(
                    select(MediaCache)
                    .where(
                        MediaCache.status == "ready",
                        MediaCache.expires_at <= now,
                    )
                    .order_by(MediaCache.expires_at)
                    .limit(100)
                    .with_for_update(skip_locked=True)
                )
            ).all()
            if not entries:
                break
            for entry in entries:
                entry.status = "deleting"
            await session.commit()
        for entry in entries:
            await remove_cache_file(entry.storage_path, media_root)
        async with _factory(ctx)() as session:
            await session.execute(
                update(MediaCache)
                .where(MediaCache.id.in_([entry.id for entry in entries]))
                .values(status="deleted")
            )
            await session.commit()
        removed += len(entries)
        if len(entries) < 100:
            break

    while True:
        async with _factory(ctx)() as session:
            total_bytes = int(
                await session.scalar(
                    select(func.coalesce(func.sum(MediaCache.file_size_bytes), 0)).where(
                        MediaCache.status == "ready"
                    )
                )
                or 0
            )
            if total_bytes <= settings.media_cache_max_bytes:
                break
            entries = (
                await session.scalars(
                    select(MediaCache)
                    .where(MediaCache.status == "ready")
                    .order_by(MediaCache.created_at)
                    .limit(50)
                    .with_for_update(skip_locked=True)
                )
            ).all()
            if not entries:
                break
            for entry in entries:
                entry.status = "deleting"
            await session.commit()
        for entry in entries:
            await remove_cache_file(entry.storage_path, media_root)
        async with _factory(ctx)() as session:
            await session.execute(
                update(MediaCache)
                .where(MediaCache.id.in_([entry.id for entry in entries]))
                .values(status="deleted")
            )
            await session.commit()
        removed += len(entries)

    await asyncio.to_thread(
        cleanup_stale_workspaces,
        media_root,
        older_than_seconds=max(settings.job_max_age_seconds * 2, 3600),
    )
    if removed:
        logger.info("cache_cleanup_completed", removed=removed)
    return removed


async def reconcile_stale_jobs(ctx: dict[str, Any]) -> int:
    settings = _settings(ctx)
    now = datetime.now(UTC)
    cutoff = now - timedelta(seconds=settings.job_max_age_seconds)
    affected = 0
    notifications: list[tuple[int, str]] = []

    async with _factory(ctx)() as session:
        rows = (
            await session.execute(
                select(DownloadJob, User)
                .join(User, DownloadJob.user_id == User.id)
                .where(
                    DownloadJob.status.in_(tuple(ACTIVE_STATUSES)),
                    DownloadJob.requested_at < cutoff,
                )
                .order_by(DownloadJob.requested_at)
                .limit(50)
                .with_for_update(of=DownloadJob, skip_locked=True)
            )
        ).all()

        for job, user in rows:
            should_fail = (
                job.status == JobStatus.DELIVERING.value
                or job.attempt_count >= settings.download_max_attempts
            )
            if should_fail:
                job.status = JobStatus.FAILED.value
                job.stage = JobStatus.FAILED.value
                job.failed_at = now
                job.error_code = ErrorCode.PROCESSING_TIMEOUT.value
                job.error_detail_safe = "The download took too long and was stopped."
                await release_quota(session, job.id, now=now)
                notifications.append(
                    (
                        user.telegram_user_id,
                        "Sorry, this download timed out. Please try again.",
                    )
                )
            else:
                job.status = JobStatus.QUEUED.value
                job.stage = JobStatus.QUEUED.value
                job.started_at = None
                job.error_code = "STALE_LEASE"
                job.error_detail_safe = "The job was requeued after a worker interruption."
                enqueue_download_requested(session, job.id, now=now)
            affected += 1
        await session.commit()

    delivery = cast(Delivery | None, ctx.get("delivery"))
    if delivery is not None:
        for chat_id, text in notifications:
            await delivery.send_text(chat_id, text)
    if affected:
        logger.info("stale_jobs_reconciled", count=affected)
    return affected


async def worker_startup(ctx: dict[Any, Any]) -> None:
    from backend.database.session import build_engine, build_session_factory

    settings = get_settings()
    ctx["settings"] = settings
    engine = build_engine(settings)
    ctx["db_engine"] = engine
    ctx["session_factory"] = build_session_factory(engine)
    ctx["adapter"] = YtDlpAdapter(
        metadata_timeout_seconds=settings.extractor_metadata_timeout_seconds,
        download_timeout_seconds=settings.extractor_download_timeout_seconds,
    )
    if settings.telegram_token:
        from telegram import Bot

        bot = Bot(token=settings.telegram_token)
        ctx["bot"] = bot
        ctx["delivery"] = BotDelivery(bot)
    else:
        ctx["bot"] = None
        ctx["delivery"] = None


async def worker_shutdown(ctx: dict[Any, Any]) -> None:
    bot = ctx.get("bot")
    if bot is not None:
        await bot.shutdown()
    engine = ctx.get("db_engine")
    if engine is not None:
        await engine.dispose()
