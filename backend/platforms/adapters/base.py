from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from backend.platforms.urls import NormalizedURL


@dataclass(frozen=True, slots=True)
class MediaFormat:
    format_id: str
    ext: str | None
    width: int | None
    height: int | None
    vcodec: str | None
    acodec: str | None
    filesize: int | None
    tbr: float | None
    protocol: str | None
    has_drm: bool = False

    @property
    def has_video(self) -> bool:
        return self.vcodec not in (None, "none")

    @property
    def has_audio(self) -> bool:
        return self.acodec not in (None, "none")


@dataclass(frozen=True, slots=True)
class MediaMetadata:
    title: str | None
    duration_seconds: float | None
    is_live: bool
    webpage_url: str | None
    extractor: str | None
    formats: tuple[MediaFormat, ...]
    availability: str | None = None
    uploader: str | None = None


@dataclass(frozen=True, slots=True)
class FormatSelection:
    format_spec: str
    video_format_id: str | None
    audio_format_id: str | None
    expected_height: int | None
    estimated_bytes: int | None
    combined: bool
    fallback_format_spec: str | None = None


class PlatformAdapter(Protocol):
    async def inspect(self, url: NormalizedURL, workspace: Path) -> MediaMetadata: ...

    async def download(
        self,
        url: NormalizedURL,
        selection: FormatSelection,
        workspace: Path,
        *,
        max_bytes: int,
    ) -> Path: ...
