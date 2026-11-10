from pathlib import Path

from apps.bot_v0 import messages
from backend.downloads.engine import PreparedDownload
from backend.media.ffprobe import ProbeResult
from backend.media.processing import PreparedMedia
from backend.platforms.adapters.base import FormatSelection, MediaMetadata
from backend.platforms.urls import NormalizedURL


def _prepared(
    title: str | None,
    *,
    uploader: str | None = "Example Channel",
    size_bytes: int = 1234,
) -> PreparedDownload:
    return PreparedDownload(
        normalized=NormalizedURL(
            url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            platform="youtube",
            content_type="public_video",
            host="www.youtube.com",
            source_id="dQw4w9WgXcQ",
        ),
        metadata=MediaMetadata(
            title=title,
            duration_seconds=12.0,
            is_live=False,
            webpage_url=None,
            extractor="youtube",
            formats=(),
            uploader=uploader,
        ),
        selection=FormatSelection(
            format_spec="18",
            video_format_id="18",
            audio_format_id=None,
            expected_height=360,
            estimated_bytes=size_bytes,
            combined=True,
        ),
        media=PreparedMedia(
            path=Path("/tmp/output.mp4"),
            probe=ProbeResult(
                duration_seconds=12.0,
                width=640,
                height=360,
                video_codec="h264",
                audio_codec="aac",
                format_name="mp4",
                size_bytes=size_bytes,
            ),
            mime_type="video/mp4",
        ),
    )


def test_success_caption_escapes_user_title() -> None:
    caption = messages.success_caption(_prepared("<script>&"))

    assert "&lt;script&gt;&amp;" in caption
    assert "<script>" not in caption
    assert "by Example Channel" in caption
    assert "YouTube · 360p" in caption
    assert "@" not in caption


def test_success_caption_survives_a_long_title() -> None:
    caption = messages.success_caption(_prepared("x" * 500))

    assert len(caption) <= 1024
    assert caption.endswith("YouTube · 360p")


def test_success_caption_omits_missing_title_and_uploader() -> None:
    caption = messages.success_caption(_prepared(None, uploader=None))

    assert "<b></b>" not in caption
    assert caption.startswith("YouTube · 360p")


def test_progress_bar_bounds() -> None:
    assert messages.progress_bar(0, 5) == "▱▱▱▱▱"
    assert messages.progress_bar(5, 5) == "▰▰▰▰▰"
    assert messages.progress_bar(3, 5) == "▰▰▰▱▱"


def test_status_card_contains_counts_and_limits() -> None:
    text = messages.status_card(
        used=2,
        limit=5,
        max_height=480,
        max_bytes=48 * 1024**2,
        max_duration_seconds=600,
    )

    assert "2 of 5 used (3 left)" in text
    assert "Quality: up to 480p" in text
    assert "Size: up to 48.0 MiB" in text


def test_quota_text_mentions_reset_timezone() -> None:
    assert "Africa/Lagos" in messages.quota_exhausted_text(5)
