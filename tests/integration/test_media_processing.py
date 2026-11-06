import asyncio
import subprocess
from pathlib import Path

import pytest

from backend.media.processing import prepare_media


def _generate_video(path: Path, size: str) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=size={size}:rate=30:duration=2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(path),
        ],
        check=True,
        capture_output=True,
    )


@pytest.mark.parametrize(
    ("size", "orientation"),
    [("1920x1080", "landscape"), ("576x1024", "portrait")],
)
async def test_prepare_media_caps_the_shorter_dimension(
    tmp_path: Path,
    size: str,
    orientation: str,
) -> None:
    source = tmp_path / "source.mp4"
    await asyncio.to_thread(_generate_video, source, size)

    prepared = await prepare_media(
        source,
        tmp_path,
        max_height=480,
        max_bytes=48 * 1024**2,
        max_duration_seconds=600,
        ffmpeg_timeout_seconds=600,
    )

    probe = prepared.probe
    assert probe.quality_height <= 480
    if orientation == "landscape":
        assert probe.width > probe.height
        assert probe.height == 480
    else:
        assert probe.height > probe.width
        assert probe.width == 480
