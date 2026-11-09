"""In-process download engine for callers that do not use the durable job pipeline."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from backend.core.config import Settings
from backend.core.errors import AppError, ErrorCode
from backend.media.processing import PreparedMedia, prepare_media
from backend.media.selection import select_format
from backend.platforms.adapters.base import FormatSelection, MediaMetadata, PlatformAdapter
from backend.platforms.adapters.ytdlp import YtDlpAdapter
from backend.platforms.urls import NormalizedURL, normalize_url, resolve_public_addresses
from backend.storage.workspace import job_workspace

STAGE_INSPECTING = "inspecting"
STAGE_DOWNLOADING = "downloading"
STAGE_PREPARING = "preparing"

StageCallback = Callable[[str], Awaitable[None]]


async def _emit(on_stage: StageCallback | None, stage: str) -> None:
    if on_stage is not None:
        await on_stage(stage)


@dataclass(frozen=True, slots=True)
class EngineLimits:
    max_height: int
    max_bytes: int
    max_duration_seconds: int
    metadata_timeout_seconds: int
    download_timeout_seconds: int
    ffmpeg_timeout_seconds: int

    @classmethod
    def free_plan(cls, settings: Settings, *, max_height: int | None = None) -> EngineLimits:
        return cls(
            max_height=max_height if max_height is not None else settings.free_max_resolution_p,
            max_bytes=min(settings.max_media_bytes, settings.telegram_upload_max_bytes),
            max_duration_seconds=settings.max_media_duration_seconds,
            metadata_timeout_seconds=settings.extractor_metadata_timeout_seconds,
            download_timeout_seconds=settings.extractor_download_timeout_seconds,
            ffmpeg_timeout_seconds=settings.ffmpeg_timeout_seconds,
        )


@dataclass(frozen=True, slots=True)
class PreparedDownload:
    normalized: NormalizedURL
    metadata: MediaMetadata
    selection: FormatSelection
    media: PreparedMedia


class InProcessEngine:
    def __init__(self, limits: EngineLimits, adapter: PlatformAdapter | None = None) -> None:
        self.limits = limits
        self.adapter = adapter or YtDlpAdapter(
            metadata_timeout_seconds=limits.metadata_timeout_seconds,
            download_timeout_seconds=limits.download_timeout_seconds,
        )

    async def validate(self, raw_url: str) -> NormalizedURL:
        normalized = normalize_url(raw_url)
        await resolve_public_addresses(normalized.host)
        return normalized

    @asynccontextmanager
    async def prepare(
        self,
        raw_url: str,
        workspace_root: Path,
        *,
        on_stage: StageCallback | None = None,
    ) -> AsyncIterator[PreparedDownload]:
        normalized = await self.validate(raw_url)
        with job_workspace(workspace_root, uuid.uuid4()) as workspace:
            await _emit(on_stage, STAGE_INSPECTING)
            metadata = await self.adapter.inspect(normalized, workspace.path)
            if metadata.is_live:
                raise AppError(ErrorCode.UNSUPPORTED_CONTENT, "Live streams are not supported.")
            if (
                metadata.duration_seconds is not None
                and metadata.duration_seconds > self.limits.max_duration_seconds
            ):
                raise AppError(
                    ErrorCode.DURATION_LIMIT,
                    "This video is longer than the supported limit.",
                )

            selection = select_format(
                metadata.formats,
                max_height=self.limits.max_height,
                max_bytes=self.limits.max_bytes,
                duration_seconds=metadata.duration_seconds,
            )
            await _emit(on_stage, STAGE_DOWNLOADING)
            source_path = await self.adapter.download(
                normalized,
                selection,
                workspace.path,
                max_bytes=self.limits.max_bytes,
            )
            await _emit(on_stage, STAGE_PREPARING)
            media = await prepare_media(
                source_path,
                workspace.path,
                max_height=self.limits.max_height,
                max_bytes=self.limits.max_bytes,
                max_duration_seconds=self.limits.max_duration_seconds,
                ffmpeg_timeout_seconds=self.limits.ffmpeg_timeout_seconds,
            )
            yield PreparedDownload(
                normalized=normalized,
                metadata=metadata,
                selection=selection,
                media=media,
            )
