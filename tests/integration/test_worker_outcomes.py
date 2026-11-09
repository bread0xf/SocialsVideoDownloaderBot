import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from structlog.testing import capture_logs

from backend.core.config import Settings
from backend.core.errors import AppError, ErrorCode
from backend.database.models import (
    DownloadJob,
    MediaCache,
    OutboxEvent,
    Plan,
    Subscription,
    UsageLedger,
    UsageReservation,
    User,
)
from backend.delivery.telegram import DeliveredMedia
from backend.downloads.cache_keys import build_media_key
from backend.downloads.service import submit_download
from backend.media.ffprobe import ProbeResult
from backend.media.processing import PreparedMedia
from backend.platforms.urls import normalize_url
from backend.workers import tasks


class _RecordingDelivery:
    def __init__(self) -> None:
        self.videos: list[tuple[int, PreparedMedia]] = []
        self.texts: list[tuple[int, str]] = []

    async def send_video(
        self,
        chat_id: int,
        media: PreparedMedia,
        *,
        caption: str | None = None,
        parse_mode: str | None = None,
    ) -> DeliveredMedia:
        self.videos.append((chat_id, media))
        return DeliveredMedia(message_id=1, file_id="cached-file-id")

    async def send_text(self, chat_id: int, text: str) -> None:
        self.texts.append((chat_id, text))


async def _user(session: AsyncSession) -> User:
    user = User(telegram_user_id=uuid.uuid4().int % 10**12)
    session.add(user)
    await session.flush()
    return user


async def _submitted_job(
    session: AsyncSession,
    *,
    settings: Settings,
    now: datetime,
) -> tuple[User, DownloadJob]:
    user = await _user(session)
    result = await submit_download(
        session,
        user=user,
        normalized_url=normalize_url("https://youtu.be/dQw4w9WgXcQ"),
        idempotency_key=f"telegram:{uuid.uuid4()}",
        now=now,
        settings=settings,
    )
    await session.commit()
    return user, result.job


def _snapshot(job: DownloadJob, user: User) -> tasks.JobSnapshot:
    return tasks.JobSnapshot(
        job_id=job.id,
        user_id=user.id,
        telegram_user_id=user.telegram_user_id,
        source_url=job.canonical_url or job.submitted_url,
        media_key=job.media_key,
        attempt_count=job.attempt_count,
    )


async def test_terminal_failure_releases_quota_without_counting(
    session_factory: async_sessionmaker[AsyncSession],
    plans: None,
    tmp_path: Path,
) -> None:
    now = datetime.now(UTC)
    settings = Settings(
        app_env="test",
        free_daily_limit=5,
        premium_daily_limit=100,
        download_max_attempts=1,
        media_root=tmp_path,
    )
    async with session_factory() as session:
        user, job = await _submitted_job(session, settings=settings, now=now)
        job = await session.scalar(
            select(DownloadJob).where(DownloadJob.id == job.id).with_for_update()
        )
        assert job is not None
        job.attempt_count = 1
        await session.commit()
        snapshot = _snapshot(job, user)

    delivery = _RecordingDelivery()
    outcome = await tasks._handle_failure(
        {"settings": settings, "session_factory": session_factory, "delivery": delivery},
        snapshot,
        AppError(ErrorCode.TELEGRAM_DELIVERY_FAILED, "Delivery failed."),
    )

    assert outcome == "failed"
    assert delivery.texts == [
        (user.telegram_user_id, "Sorry, this download failed. Delivery failed.")
    ]
    async with session_factory() as session:
        job = await session.scalar(select(DownloadJob).where(DownloadJob.id == snapshot.job_id))
        reservation = await session.scalar(
            select(UsageReservation).where(UsageReservation.download_job_id == snapshot.job_id)
        )
        commit_entries = await session.scalar(
            select(func.count(UsageLedger.id)).where(
                UsageLedger.idempotency_key == f"download:{snapshot.job_id}:commit"
            )
        )
        release_entries = await session.scalar(
            select(func.count(UsageLedger.id)).where(
                UsageLedger.idempotency_key == f"download:{snapshot.job_id}:release"
            )
        )
        assert job is not None
        assert job.status == "failed"
        assert job.error_code == ErrorCode.TELEGRAM_DELIVERY_FAILED.value
        assert reservation is not None
        assert reservation.status == "released"
        assert commit_entries == 0
        assert release_entries == 1


async def test_retryable_failure_requeues_without_releasing_quota(
    session_factory: async_sessionmaker[AsyncSession],
    plans: None,
    tmp_path: Path,
) -> None:
    now = datetime.now(UTC)
    settings = Settings(
        app_env="test",
        free_daily_limit=5,
        premium_daily_limit=100,
        download_max_attempts=3,
        media_root=tmp_path,
    )
    async with session_factory() as session:
        user, job = await _submitted_job(session, settings=settings, now=now)
        job = await session.scalar(
            select(DownloadJob).where(DownloadJob.id == job.id).with_for_update()
        )
        assert job is not None
        job.status = "extracting"
        job.stage = "extracting"
        job.attempt_count = 1
        initial_events = await session.scalar(
            select(func.count(OutboxEvent.id)).where(OutboxEvent.aggregate_id == job.id)
        )
        await session.commit()
        snapshot = _snapshot(job, user)

    outcome = await tasks._handle_failure(
        {"settings": settings, "session_factory": session_factory, "delivery": None},
        snapshot,
        AppError(ErrorCode.TEMPORARY_FAILURE, "Try again."),
    )

    assert outcome == "retry"
    async with session_factory() as session:
        job = await session.scalar(select(DownloadJob).where(DownloadJob.id == snapshot.job_id))
        reservation = await session.scalar(
            select(UsageReservation).where(UsageReservation.download_job_id == snapshot.job_id)
        )
        events = await session.scalar(
            select(func.count(OutboxEvent.id)).where(OutboxEvent.aggregate_id == snapshot.job_id)
        )
        assert job is not None
        assert job.status == "queued"
        assert job.error_code == ErrorCode.TEMPORARY_FAILURE.value
        assert reservation is not None
        assert reservation.status == "reserved"
        assert events == initial_events + 1


async def test_cache_hit_rechecks_entitlement_before_reusing_media(
    session_factory: async_sessionmaker[AsyncSession],
    plans: None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)
    settings = Settings(
        app_env="test",
        free_daily_limit=5,
        premium_daily_limit=100,
        premium_max_resolution_p=2160,
        media_root=tmp_path,
    )
    async with session_factory() as session:
        user = await _user(session)
        premium_plan = await session.scalar(select(Plan).where(Plan.code == "premium"))
        assert premium_plan is not None
        subscription = Subscription(
            user_id=user.id,
            plan_id=premium_plan.id,
            provider="test",
            status="active",
            paid_through=now + timedelta(hours=1),
        )
        session.add(subscription)
        await session.flush()

        normalized = normalize_url("https://youtu.be/dQw4w9WgXcQ")
        submitted = await submit_download(
            session,
            user=user,
            normalized_url=normalized,
            idempotency_key="premium-then-expired",
            now=now,
            settings=settings,
        )
        assert submitted.entitlement is not None
        assert submitted.entitlement.output_profile == "premium-2160p"

        subscription.paid_through = now - timedelta(hours=1)

        free_key = build_media_key(
            platform=normalized.platform,
            source_id=normalized.source_id,
            output_profile="free-480p",
            processing_version=settings.processing_version,
        )
        premium_key = build_media_key(
            platform=normalized.platform,
            source_id=normalized.source_id,
            output_profile="premium-2160p",
            processing_version=settings.processing_version,
        )
        cache_root = tmp_path / "cache"
        cache_root.mkdir()
        free_file = cache_root / f"{free_key}.mp4"
        free_content = b"free media"
        free_file.write_bytes(free_content)
        premium_file = cache_root / f"{premium_key}.mp4"
        premium_content = b"premium media"
        premium_file.write_bytes(premium_content)
        for media_key, storage_path, output_profile, content in (
            (free_key, free_file, "free-480p", free_content),
            (premium_key, premium_file, "premium-2160p", premium_content),
        ):
            session.add(
                MediaCache(
                    media_key=media_key,
                    platform=normalized.platform,
                    source_identity_hash="source-hash",
                    output_profile=output_profile,
                    processing_version=settings.processing_version,
                    storage_path=str(storage_path),
                    file_size_bytes=len(content),
                    mime_type="video/mp4",
                    expires_at=now + timedelta(hours=1),
                    status="ready",
                )
            )
        await session.commit()
        job_id = submitted.job.id

    async def _fake_probe(path: Path, *, timeout_seconds: int = 30) -> ProbeResult:
        del timeout_seconds
        stat_result = await asyncio.to_thread(path.stat)
        return ProbeResult(
            duration_seconds=5.0,
            width=854,
            height=480,
            video_codec="h264",
            audio_codec="aac",
            format_name="mp4",
            size_bytes=stat_result.st_size,
        )

    monkeypatch.setattr(tasks, "probe_media", _fake_probe)
    delivery = _RecordingDelivery()
    with capture_logs() as logs:
        outcome = await tasks.process_download(
            {
                "settings": settings,
                "session_factory": session_factory,
                "delivery": delivery,
                "adapter": None,
            },
            str(job_id),
        )

    assert outcome == "completed"
    completed_logs = [entry for entry in logs if entry["event"] == "download_completed"]
    assert len(completed_logs) == 1
    assert completed_logs[0]["cache_hit"] is True
    assert isinstance(completed_logs[0]["elapsed_ms"], int)
    assert completed_logs[0]["output_bytes"] == len(free_content)
    assert completed_logs[0]["resolution_p"] == 480
    assert completed_logs[0]["platform"] == "youtube"
    assert len(delivery.videos) == 1
    delivered_media = delivery.videos[0][1]
    assert delivered_media.path == free_file
    assert delivered_media.path != premium_file

    async with session_factory() as session:
        job = await session.scalar(select(DownloadJob).where(DownloadJob.id == job_id))
        assert job is not None
        assert job.status == "completed"
        assert job.selected_resolution_p == 480
        assert job.media_key == free_key
