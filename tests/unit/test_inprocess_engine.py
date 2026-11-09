from __future__ import annotations

from pathlib import Path

import pytest

from backend.core.errors import AppError, ErrorCode
from backend.downloads import engine as engine_module
from backend.downloads.engine import EngineLimits, InProcessEngine
from backend.media.ffprobe import ProbeResult
from backend.media.processing import PreparedMedia
from backend.platforms.adapters.base import FormatSelection, MediaFormat, MediaMetadata
from backend.platforms.urls import NormalizedURL

LIMITS = EngineLimits(
    max_height=480,
    max_bytes=10_000_000,
    max_duration_seconds=600,
    metadata_timeout_seconds=5,
    download_timeout_seconds=5,
    ffmpeg_timeout_seconds=5,
)

YOUTUBE_URL = "https://youtu.be/dQw4w9WgXcQ"


def _format() -> MediaFormat:
    return MediaFormat(
        format_id="18",
        ext="mp4",
        width=640,
        height=360,
        vcodec="h264",
        acodec="aac",
        filesize=1_000_000,
        tbr=500.0,
        protocol="https",
    )


def _metadata(*, duration: float | None = 12.0, is_live: bool = False) -> MediaMetadata:
    return MediaMetadata(
        title="Example",
        duration_seconds=duration,
        is_live=is_live,
        webpage_url=None,
        extractor="youtube",
        formats=(_format(),),
    )


class _FakeAdapter:
    def __init__(self, metadata: MediaMetadata) -> None:
        self.metadata = metadata
        self.calls: list[tuple[object, ...]] = []

    async def inspect(self, url: NormalizedURL, workspace: Path) -> MediaMetadata:
        self.calls.append(("inspect", url, workspace))
        return self.metadata

    async def download(
        self,
        url: NormalizedURL,
        selection: FormatSelection,
        workspace: Path,
        *,
        max_bytes: int,
    ) -> Path:
        self.calls.append(("download", url, max_bytes))
        source = workspace / "source.mp4"
        source.write_bytes(b"source")
        return source


@pytest.fixture(autouse=True)
def _stub_network_and_ffmpeg(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _resolve(host: str) -> tuple[str, ...]:
        return ("93.184.216.34",)

    async def _prepare(
        source: Path,
        workspace: Path,
        *,
        max_height: int,
        max_bytes: int,
        max_duration_seconds: int,
        ffmpeg_timeout_seconds: int = 600,
    ) -> PreparedMedia:
        return PreparedMedia(
            path=workspace / "output.mp4",
            probe=ProbeResult(
                duration_seconds=12.0,
                width=640,
                height=360,
                video_codec="h264",
                audio_codec="aac",
                format_name="mp4",
                size_bytes=1234,
            ),
            mime_type="video/mp4",
        )

    monkeypatch.setattr(engine_module, "resolve_public_addresses", _resolve)
    monkeypatch.setattr(engine_module, "prepare_media", _prepare)


async def test_prepare_returns_selection_and_media(tmp_path: Path) -> None:
    adapter = _FakeAdapter(_metadata())
    engine = InProcessEngine(LIMITS, adapter=adapter)

    async with engine.prepare(YOUTUBE_URL, tmp_path) as prepared:
        assert prepared.normalized.platform == "youtube"
        assert prepared.selection.format_spec == "18"
        assert prepared.selection.expected_height == 360
        assert prepared.media.mime_type == "video/mp4"

    assert adapter.calls[0][0] == "inspect"
    assert adapter.calls[1] == ("download", prepared.normalized, LIMITS.max_bytes)


async def test_workspace_is_removed_after_success(tmp_path: Path) -> None:
    engine = InProcessEngine(LIMITS, adapter=_FakeAdapter(_metadata()))

    async with engine.prepare(YOUTUBE_URL, tmp_path):
        assert list((tmp_path / "workspaces").iterdir())

    assert list((tmp_path / "workspaces").iterdir()) == []


async def test_rejects_live_stream_without_downloading(tmp_path: Path) -> None:
    adapter = _FakeAdapter(_metadata(is_live=True))
    engine = InProcessEngine(LIMITS, adapter=adapter)

    with pytest.raises(AppError) as info:
        async with engine.prepare(YOUTUBE_URL, tmp_path):
            pass

    assert info.value.code is ErrorCode.UNSUPPORTED_CONTENT
    assert [call[0] for call in adapter.calls] == ["inspect"]
    assert list((tmp_path / "workspaces").iterdir()) == []


async def test_rejects_overlong_video(tmp_path: Path) -> None:
    engine = InProcessEngine(LIMITS, adapter=_FakeAdapter(_metadata(duration=601.0)))

    with pytest.raises(AppError) as info:
        async with engine.prepare(YOUTUBE_URL, tmp_path):
            pass

    assert info.value.code is ErrorCode.DURATION_LIMIT


async def test_reports_stages_in_order(tmp_path: Path) -> None:
    stages: list[str] = []

    async def on_stage(stage: str) -> None:
        stages.append(stage)

    engine = InProcessEngine(LIMITS, adapter=_FakeAdapter(_metadata()))

    async with engine.prepare(YOUTUBE_URL, tmp_path, on_stage=on_stage):
        pass

    assert stages == ["inspecting", "downloading", "preparing"]


async def test_rejects_unsupported_host_before_extraction(tmp_path: Path) -> None:
    adapter = _FakeAdapter(_metadata())
    engine = InProcessEngine(LIMITS, adapter=adapter)

    with pytest.raises(AppError) as info:
        async with engine.prepare("https://example.com/video/1", tmp_path):
            pass

    assert info.value.code is ErrorCode.UNSUPPORTED_PLATFORM
    assert adapter.calls == []
