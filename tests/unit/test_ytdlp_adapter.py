from pathlib import Path

import pytest

from backend.core.errors import AppError, ErrorCode
from backend.platforms.adapters.ytdlp import (
    _collect_output_file,
    classify_failure,
    parse_metadata,
)


def _format(
    format_id: str,
    *,
    ext: str = "mp4",
    width: int | None = 854,
    height: int | None = 480,
    vcodec: str | None = "avc1.64001F",
    acodec: str | None = "none",
    filesize: int | None = None,
    filesize_approx: int | None = None,
    tbr: float | None = 500.0,
    protocol: str = "https",
    has_drm: bool = False,
) -> dict[str, object]:
    return {
        "format_id": format_id,
        "ext": ext,
        "width": width,
        "height": height,
        "vcodec": vcodec,
        "acodec": acodec,
        "filesize": filesize,
        "filesize_approx": filesize_approx,
        "tbr": tbr,
        "protocol": protocol,
        "has_drm": has_drm,
    }


def _metadata(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "_type": "video",
        "id": "abc123",
        "title": "Example",
        "duration": 120.0,
        "is_live": False,
        "live_status": "not_live",
        "availability": "public",
        "webpage_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "extractor": "youtube",
        "extractor_key": "Youtube",
        "formats": [
            _format("137", height=1080, filesize=50_000_000, tbr=4000.0),
            _format("140", ext="m4a", width=None, height=None, vcodec="none", acodec="mp4a.40.2"),
        ],
    }
    data.update(overrides)
    return data


def test_parses_youtube_separate_streams() -> None:
    metadata = parse_metadata(_metadata())

    assert metadata.title == "Example"
    assert metadata.duration_seconds == 120.0
    assert metadata.extractor == "Youtube"
    assert metadata.webpage_url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert len(metadata.formats) == 2
    assert metadata.formats[0].height == 1080
    assert metadata.formats[1].has_audio is True


def test_parses_tiktok_combined_format() -> None:
    metadata = parse_metadata(
        _metadata(
            webpage_url="https://www.tiktok.com/@creator/video/1234567890",
            extractor_key="TikTok",
            formats=[
                _format(
                    "download",
                    height=720,
                    width=1280,
                    vcodec="h264",
                    acodec="aac",
                    filesize=4_000_000,
                )
            ],
        )
    )

    assert metadata.extractor == "TikTok"
    assert metadata.formats[0].has_video is True
    assert metadata.formats[0].has_audio is True
    assert metadata.formats[0].filesize == 4_000_000


def test_parses_instagram_reel() -> None:
    metadata = parse_metadata(
        _metadata(
            webpage_url="https://www.instagram.com/reel/AbCdEf123/",
            extractor_key="Instagram",
            formats=[
                _format(
                    "mp4-480",
                    height=480,
                    vcodec="h264",
                    acodec="aac",
                    filesize=2_000_000,
                )
            ],
        )
    )

    assert metadata.extractor == "Instagram"
    assert metadata.formats[0].height == 480


def test_parses_facebook_video() -> None:
    metadata = parse_metadata(
        _metadata(
            webpage_url="https://www.facebook.com/watch/?v=1234567890",
            extractor_key="Facebook",
            formats=[
                _format(
                    "sd",
                    height=360,
                    width=640,
                    vcodec="h264",
                    acodec="aac",
                    filesize=1_500_000,
                )
            ],
        )
    )

    assert metadata.extractor == "Facebook"
    assert metadata.formats[0].filesize == 1_500_000


def test_detects_live_stream() -> None:
    metadata = parse_metadata(_metadata(is_live=True, live_status="is_live"))

    assert metadata.is_live is True


def test_rejects_private_availability() -> None:
    with pytest.raises(AppError) as exc_info:
        parse_metadata(_metadata(availability="private"))

    assert exc_info.value.code == ErrorCode.PRIVATE_OR_RESTRICTED_CONTENT


def test_rejects_drm_content() -> None:
    with pytest.raises(AppError) as exc_info:
        parse_metadata(_metadata(_has_drm=True))

    assert exc_info.value.code == ErrorCode.PRIVATE_OR_RESTRICTED_CONTENT


def test_rejects_multi_video_playlist() -> None:
    with pytest.raises(AppError) as exc_info:
        parse_metadata(
            _metadata(
                _type="playlist",
                entries=[_metadata(), _metadata()],
            )
        )

    assert exc_info.value.code == ErrorCode.UNSUPPORTED_CONTENT


def test_accepts_single_video_carousel_entry() -> None:
    metadata = parse_metadata(
        _metadata(
            _type="playlist",
            entries=[
                {
                    "id": "entry-1",
                    "duration": 15.0,
                    "webpage_url": "https://www.instagram.com/reel/AbCdEf123/",
                    "extractor_key": "Instagram",
                    "formats": [
                        _format(
                            "mp4-480",
                            height=480,
                            vcodec="h264",
                            acodec="aac",
                            filesize=1_000_000,
                        )
                    ],
                }
            ],
        )
    )

    assert metadata.duration_seconds == 15.0
    assert metadata.webpage_url == "https://www.instagram.com/reel/AbCdEf123/"
    assert len(metadata.formats) == 1


def test_treats_zero_filesize_as_unknown() -> None:
    metadata = parse_metadata(
        _metadata(formats=[_format("137", height=480, filesize=None, filesize_approx=0)])
    )

    assert metadata.formats[0].filesize is None


@pytest.mark.parametrize(
    ("stderr", "expected"),
    [
        (
            "ERROR: Private video. Sign in if you've been granted access",
            ErrorCode.PRIVATE_OR_RESTRICTED_CONTENT,
        ),
        ("ERROR: Sign in to confirm you're not a bot", ErrorCode.PRIVATE_OR_RESTRICTED_CONTENT),
        ("ERROR: This live event has ended", ErrorCode.UNSUPPORTED_CONTENT),
        ("ERROR: File is larger than max-filesize", ErrorCode.FILE_TOO_LARGE),
        ("ERROR: Requested format is not available", ErrorCode.UNSUPPORTED_CONTENT),
        ("ERROR: Video unavailable", ErrorCode.SOURCE_UNAVAILABLE),
        ("ERROR: HTTP Error 404: Not Found", ErrorCode.SOURCE_UNAVAILABLE),
        ("ERROR: HTTP Error 429: Too Many Requests", ErrorCode.TEMPORARY_FAILURE),
        ("ERROR: Unable to extract player response", ErrorCode.TEMPORARY_FAILURE),
    ],
)
def test_classifies_extractor_failures(stderr: str, expected: ErrorCode) -> None:
    assert classify_failure(stderr).code == expected


def test_collects_single_video_file(tmp_path: Path) -> None:
    video = tmp_path / "download.mp4"
    video.write_bytes(b"video")

    assert _collect_output_file(tmp_path, max_bytes=100) == video


def test_rejects_oversized_output(tmp_path: Path) -> None:
    video = tmp_path / "download.mp4"
    video.write_bytes(b"x" * 20)

    with pytest.raises(AppError) as exc_info:
        _collect_output_file(tmp_path, max_bytes=10)

    assert exc_info.value.code == ErrorCode.FILE_TOO_LARGE
    assert not video.exists()


def test_rejects_multiple_outputs(tmp_path: Path) -> None:
    (tmp_path / "one.mp4").write_bytes(b"one")
    (tmp_path / "two.webm").write_bytes(b"two")

    with pytest.raises(AppError) as exc_info:
        _collect_output_file(tmp_path, max_bytes=100)

    assert exc_info.value.code == ErrorCode.INTERNAL_ERROR


def test_skips_symlinks_that_escape_workspace(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.mp4"
    outside.write_bytes(b"outside")
    (tmp_path / "link.mp4").symlink_to(outside)

    with pytest.raises(AppError) as exc_info:
        _collect_output_file(tmp_path, max_bytes=100)

    assert exc_info.value.code == ErrorCode.INTERNAL_ERROR
