import pytest

from backend.core.errors import AppError, ErrorCode
from backend.media.selection import select_format
from backend.platforms.adapters.base import MediaFormat


def _format(
    format_id: str,
    *,
    height: int | None = 480,
    width: int | None = 854,
    ext: str | None = "mp4",
    vcodec: str | None = "h264",
    acodec: str | None = "none",
    filesize: int | None = 10_000_000,
    tbr: float | None = 500.0,
    protocol: str | None = "https",
    has_drm: bool = False,
) -> MediaFormat:
    return MediaFormat(
        format_id=format_id,
        ext=ext,
        width=width,
        height=height,
        vcodec=vcodec,
        acodec=acodec,
        filesize=filesize,
        tbr=tbr,
        protocol=protocol,
        has_drm=has_drm,
    )


def test_selects_highest_quality_combined_format_within_ceiling() -> None:
    selection = select_format(
        (
            _format("combined-360", height=360, width=640, acodec="aac"),
            _format("combined-480", height=480, acodec="aac"),
            _format("combined-720", height=720, width=1280, acodec="aac"),
        ),
        max_height=480,
        max_bytes=100_000_000,
    )

    assert selection.format_spec == "combined-480"
    assert selection.combined is True
    assert selection.expected_height == 480


def test_prefers_h264_mp4_when_quality_is_equal() -> None:
    selection = select_format(
        (
            _format(
                "vp9-webm",
                ext="webm",
                vcodec="vp9",
                acodec="aac",
                filesize=9_000_000,
                tbr=900.0,
            ),
            _format("h264-mp4", acodec="aac", filesize=10_000_000, tbr=500.0),
        ),
        max_height=480,
        max_bytes=100_000_000,
    )

    assert selection.format_spec == "h264-mp4"


def test_falls_back_to_video_plus_audio_streams() -> None:
    selection = select_format(
        (
            _format("video-only", height=480, acodec="none", filesize=10_000_000),
            _format(
                "audio-only",
                height=None,
                width=None,
                vcodec="none",
                acodec="aac",
                filesize=1_000_000,
            ),
        ),
        max_height=480,
        max_bytes=100_000_000,
    )

    assert selection.format_spec == "video-only+audio-only"
    assert selection.video_format_id == "video-only"
    assert selection.audio_format_id == "audio-only"
    assert selection.combined is False
    assert selection.estimated_bytes == 11_000_000


def test_combined_format_wins_on_equal_height() -> None:
    selection = select_format(
        (
            _format("combined-480", acodec="aac", filesize=10_000_000),
            _format("video-480", acodec="none", filesize=9_000_000),
            _format(
                "audio",
                height=None,
                width=None,
                vcodec="none",
                acodec="aac",
                filesize=1_000_000,
            ),
        ),
        max_height=480,
        max_bytes=100_000_000,
    )

    assert selection.format_spec == "combined-480"


def test_higher_separate_streams_are_preferred_over_lower_combined() -> None:
    selection = select_format(
        (
            _format("combined-360", height=360, acodec="aac"),
            _format("video-480", height=480, acodec="none"),
            _format("audio", height=None, width=None, vcodec="none", acodec="aac"),
        ),
        max_height=480,
        max_bytes=100_000_000,
    )

    assert selection.format_spec == "video-480+audio"


def test_downscales_when_no_source_quality_fits_ceiling() -> None:
    selection = select_format(
        (_format("hd", height=1080, width=1920, acodec="aac"),),
        max_height=480,
        max_bytes=100_000_000,
    )

    assert selection.format_spec == "hd"
    assert selection.expected_height == 480


def test_quality_ceiling_uses_shorter_dimension_for_portrait_video() -> None:
    selection = select_format(
        (_format("portrait", height=840, width=472, acodec="aac"),),
        max_height=480,
        max_bytes=100_000_000,
    )

    assert selection.format_spec == "portrait"
    assert selection.expected_height == 472


def test_downscales_portrait_when_only_larger_sources_exist() -> None:
    selection = select_format(
        (_format("portrait-540", height=1024, width=576, acodec="aac"),),
        max_height=480,
        max_bytes=100_000_000,
    )

    assert selection.format_spec == "portrait-540"
    assert selection.expected_height == 480


def test_selects_silent_video_when_source_has_no_audio_stream() -> None:
    selection = select_format(
        (_format("silent", acodec="none"),),
        max_height=480,
        max_bytes=100_000_000,
    )

    assert selection.format_spec == "silent"
    assert selection.audio_format_id is None
    assert selection.combined is False


def test_rejects_when_only_candidate_exceeds_size_limit() -> None:
    with pytest.raises(AppError) as exc_info:
        select_format(
            (_format("large", acodec="aac", filesize=200_000_000),),
            max_height=480,
            max_bytes=100_000_000,
        )

    assert exc_info.value.code == ErrorCode.FILE_TOO_LARGE


def test_rejects_separate_streams_when_combined_size_exceeds_limit() -> None:
    with pytest.raises(AppError) as exc_info:
        select_format(
            (
                _format("video", acodec="none", filesize=99_000_000),
                _format(
                    "audio",
                    height=None,
                    width=None,
                    vcodec="none",
                    acodec="aac",
                    filesize=2_000_000,
                ),
            ),
            max_height=480,
            max_bytes=100_000_000,
        )

    assert exc_info.value.code == ErrorCode.FILE_TOO_LARGE


def test_ignores_unsafe_format_ids() -> None:
    with pytest.raises(AppError) as exc_info:
        select_format(
            (
                _format("../../etc/passwd", acodec="aac"),
                _format("format with spaces", acodec="aac"),
            ),
            max_height=480,
            max_bytes=100_000_000,
        )

    assert exc_info.value.code == ErrorCode.UNSUPPORTED_CONTENT


def test_accepts_unknown_size_when_no_explicit_limit_is_exceeded() -> None:
    selection = select_format(
        (_format("unknown-size", acodec="aac", filesize=None),),
        max_height=480,
        max_bytes=100_000_000,
    )

    assert selection.format_spec == "unknown-size"
    assert selection.estimated_bytes is None


def test_prefers_real_h264_codec_name() -> None:
    selection = select_format(
        (
            _format("vp9", ext="webm", vcodec="vp9", filesize=9_000_000, tbr=900.0),
            _format("avc", vcodec="avc1.64001F", filesize=10_000_000, tbr=500.0),
            _format(
                "audio",
                height=None,
                width=None,
                vcodec="none",
                acodec="mp4a.40.2",
                filesize=1_000_000,
            ),
        ),
        max_height=480,
        max_bytes=100_000_000,
    )

    assert selection.format_spec == "avc+audio"


def test_estimates_size_from_bitrate_and_duration() -> None:
    formats = (_format("combined", acodec="aac", filesize=None, tbr=500.0),)

    with pytest.raises(AppError) as exc_info:
        select_format(
            formats,
            max_height=480,
            max_bytes=3_000_000,
            duration_seconds=60.0,
        )
    assert exc_info.value.code == ErrorCode.FILE_TOO_LARGE

    selection = select_format(
        formats,
        max_height=480,
        max_bytes=4_000_000,
        duration_seconds=60.0,
    )
    assert selection.estimated_bytes == 3_750_000


def test_excludes_drm_video_formats() -> None:
    selection = select_format(
        (
            _format("drm-720", height=720, width=1280, acodec="aac", has_drm=True),
            _format("plain-360", height=360, width=640, acodec="aac"),
        ),
        max_height=720,
        max_bytes=100_000_000,
    )

    assert selection.format_spec == "plain-360"
    assert selection.expected_height == 360


def test_rejects_when_all_video_formats_are_drm() -> None:
    with pytest.raises(AppError) as exc_info:
        select_format(
            (_format("drm", acodec="aac", has_drm=True),),
            max_height=480,
            max_bytes=100_000_000,
        )

    assert exc_info.value.code == ErrorCode.PRIVATE_OR_RESTRICTED_CONTENT


def test_selects_audio_variant_that_keeps_pair_within_limit() -> None:
    selection = select_format(
        (
            _format("video", acodec="none", filesize=10_000_000),
            _format(
                "audio-large",
                height=None,
                width=None,
                vcodec="none",
                acodec="aac",
                filesize=5_000_000,
                tbr=300.0,
            ),
            _format(
                "audio-small",
                height=None,
                width=None,
                vcodec="none",
                acodec="aac",
                filesize=1_000_000,
                tbr=100.0,
            ),
        ),
        max_height=480,
        max_bytes=12_000_000,
    )

    assert selection.format_spec == "video+audio-small"


def test_combined_selection_has_height_bounded_fallback() -> None:
    selection = select_format(
        (_format("combined", acodec="aac"),),
        max_height=480,
        max_bytes=100_000_000,
    )

    assert selection.fallback_format_spec == "best[height<=480]/best[width<=480]"


def test_separate_selection_has_height_bounded_fallback() -> None:
    selection = select_format(
        (
            _format("video", acodec="none"),
            _format(
                "audio",
                height=None,
                width=None,
                vcodec="none",
                acodec="aac",
            ),
        ),
        max_height=480,
        max_bytes=100_000_000,
    )

    assert selection.fallback_format_spec == "video+bestaudio/best[height<=480]/best[width<=480]"


def test_accepts_hls_formats_with_bitrate_metadata() -> None:
    selection = select_format(
        (
            _format(
                "hls",
                acodec="aac",
                filesize=None,
                tbr=800.0,
                protocol="m3u8_native",
            ),
        ),
        max_height=480,
        max_bytes=1_000_000,
        duration_seconds=8.0,
    )

    assert selection.format_spec == "hls"
    assert selection.estimated_bytes == 800_000
