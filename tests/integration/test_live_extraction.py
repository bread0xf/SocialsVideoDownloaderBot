import os
from pathlib import Path

import pytest

from backend.media.processing import prepare_media
from backend.media.selection import select_format
from backend.platforms.adapters.ytdlp import YtDlpAdapter
from backend.platforms.urls import normalize_url

_LIVE_ENABLED = os.getenv("SVDB_LIVE_EXTRACTION") == "1"
_SAMPLE_ENV_VARS = (
    "YOUTUBE_SAMPLE_URL",
    "TIKTOK_SAMPLE_URL",
    "INSTAGRAM_SAMPLE_URL",
    "FACEBOOK_SAMPLE_URL",
)


@pytest.mark.skipif(
    not _LIVE_ENABLED,
    reason="set SVDB_LIVE_EXTRACTION=1 and platform sample URLs to run",
)
@pytest.mark.parametrize("env_var", _SAMPLE_ENV_VARS)
async def test_live_platform_metadata(env_var: str, tmp_path: Path) -> None:
    raw_url = os.getenv(env_var)
    if not raw_url:
        pytest.skip(f"{env_var} is not set")

    normalized = normalize_url(raw_url)
    adapter = YtDlpAdapter(
        metadata_timeout_seconds=60,
        download_timeout_seconds=900,
    )
    metadata = await adapter.inspect(normalized, tmp_path)

    assert metadata.formats
    assert metadata.is_live is False
    selection = select_format(
        metadata.formats,
        max_height=480,
        max_bytes=48 * 1024**2,
        duration_seconds=metadata.duration_seconds,
    )
    assert selection.format_spec


@pytest.mark.skipif(
    not _LIVE_ENABLED or not os.getenv("SVDB_LIVE_DOWNLOAD_URL"),
    reason="set SVDB_LIVE_EXTRACTION=1 and SVDB_LIVE_DOWNLOAD_URL to run",
)
async def test_live_download_and_size_cap(tmp_path: Path) -> None:
    normalized = normalize_url(os.environ["SVDB_LIVE_DOWNLOAD_URL"])
    adapter = YtDlpAdapter(
        metadata_timeout_seconds=60,
        download_timeout_seconds=900,
    )
    metadata = await adapter.inspect(normalized, tmp_path)
    max_bytes = 48 * 1024**2
    selection = select_format(
        metadata.formats,
        max_height=480,
        max_bytes=max_bytes,
        duration_seconds=metadata.duration_seconds,
    )

    output = await adapter.download(
        normalized,
        selection,
        tmp_path,
        max_bytes=max_bytes,
    )

    assert output.exists()
    assert 0 < output.stat().st_size <= max_bytes

    prepared = await prepare_media(
        output,
        tmp_path,
        max_height=480,
        max_bytes=max_bytes,
        max_duration_seconds=600,
        ffmpeg_timeout_seconds=600,
    )
    assert prepared.probe.quality_height <= 480
    assert prepared.probe.size_bytes <= max_bytes
