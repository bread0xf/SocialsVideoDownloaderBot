import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import Settings, get_settings
from backend.core.errors import AppError, ErrorCode
from backend.database.models import DownloadJob, User
from backend.downloads.cache_keys import build_media_key
from backend.downloads.outbox import enqueue_download_requested
from backend.downloads.state import ACTIVE_STATUSES, JobStatus
from backend.entitlements.service import Entitlement, resolve_entitlement
from backend.platforms.registry import platform_registry
from backend.platforms.urls import NormalizedURL
from backend.usage.service import lock_user_quota, reserve_quota


@dataclass(frozen=True, slots=True)
class SubmissionResult:
    job: DownloadJob
    created: bool
    entitlement: Entitlement | None


async def submit_download(
    session: AsyncSession,
    *,
    user: User,
    normalized_url: NormalizedURL,
    idempotency_key: str,
    now: datetime | None = None,
    settings: Settings | None = None,
) -> SubmissionResult:
    settings = settings or get_settings()
    now = now or datetime.now(UTC)

    platform_registry.require_accepting(normalized_url.platform, normalized_url.content_type)
    await lock_user_quota(session, user.id)

    existing = await session.scalar(
        select(DownloadJob).where(
            DownloadJob.user_id == user.id,
            DownloadJob.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        return SubmissionResult(job=existing, created=False, entitlement=None)

    active_jobs = await session.scalar(
        select(func.count(DownloadJob.id)).where(
            DownloadJob.user_id == user.id,
            DownloadJob.status.in_(tuple(ACTIVE_STATUSES)),
        )
    )
    if int(active_jobs or 0) >= settings.max_active_jobs_per_user:
        raise AppError(
            ErrorCode.TEMPORARY_FAILURE,
            "You already have downloads in progress. Please wait for them to finish.",
        )

    entitlement = await resolve_entitlement(session, user.id, now=now, settings=settings)
    job_id = uuid.uuid4()
    media_key = build_media_key(
        platform=normalized_url.platform,
        source_id=normalized_url.source_id,
        output_profile=entitlement.output_profile,
        processing_version=settings.processing_version,
    )
    job = DownloadJob(
        id=job_id,
        user_id=user.id,
        platform=normalized_url.platform,
        submitted_url=normalized_url.url,
        canonical_url=normalized_url.url,
        media_key=media_key,
        status=JobStatus.QUEUED.value,
        stage=JobStatus.QUEUED.value,
        requested_at=now,
        attempt_count=0,
        idempotency_key=idempotency_key,
    )
    session.add(job)
    await session.flush()

    await reserve_quota(
        session,
        user_id=user.id,
        download_job_id=job.id,
        entitlement=entitlement,
        now=now,
    )
    enqueue_download_requested(session, job.id, now=now)
    await session.flush()
    return SubmissionResult(job=job, created=True, entitlement=entitlement)
