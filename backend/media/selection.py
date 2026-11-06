import re

from backend.core.errors import AppError, ErrorCode
from backend.platforms.adapters.base import FormatSelection, MediaFormat

_SAFE_FORMAT_ID = re.compile(r"^[A-Za-z0-9_.:=@-]+$")
_H264_PREFIXES = ("avc", "h264")
_AAC_PREFIXES = ("mp4a", "aac")
_HTTP_PROTOCOLS = frozenset({None, "http", "https", "m3u8", "m3u8_native"})


def _safe_format_id(value: str | None) -> str | None:
    if not value or not _SAFE_FORMAT_ID.match(value):
        return None
    return value


def _estimated_size(fmt: MediaFormat, duration_seconds: float | None) -> int | None:
    if fmt.filesize is not None and fmt.filesize > 0:
        return fmt.filesize
    if fmt.tbr is not None and fmt.tbr > 0 and duration_seconds and duration_seconds > 0:
        return int(fmt.tbr * 1000 / 8 * duration_seconds)
    return None


def _quality_height(fmt: MediaFormat) -> int | None:
    if fmt.width is None or fmt.height is None or fmt.width <= 0 or fmt.height <= 0:
        return None
    return min(fmt.width, fmt.height)


def _codec_score(fmt: MediaFormat) -> int:
    video = (fmt.vcodec or "").lower()
    audio = (fmt.acodec or "").lower()
    score = 0
    if fmt.ext == "mp4":
        score += 1
    if video.startswith(_H264_PREFIXES):
        score += 4
    if audio.startswith(_AAC_PREFIXES):
        score += 2
    if fmt.protocol in _HTTP_PROTOCOLS:
        score += 1
    return score


def _eligible_video(fmt: MediaFormat, max_height: int) -> bool:
    quality_height = _quality_height(fmt)
    if fmt.has_drm or not fmt.has_video or quality_height is None:
        return False
    if quality_height > max_height:
        return False
    return _safe_format_id(fmt.format_id) is not None


def _video_sort_key(
    fmt: MediaFormat, duration_seconds: float | None
) -> tuple[int, int, float, int]:
    return (
        _quality_height(fmt) or 0,
        _codec_score(fmt),
        fmt.tbr or 0.0,
        _estimated_size(fmt, duration_seconds) or 0,
    )


def _audio_sort_key(fmt: MediaFormat, duration_seconds: float | None) -> tuple[int, float, int]:
    return (
        1 if (fmt.acodec or "").lower().startswith(_AAC_PREFIXES) else 0,
        fmt.tbr or 0.0,
        _estimated_size(fmt, duration_seconds) or 0,
    )


def _fits(size: int | None, max_bytes: int) -> bool:
    return size is None or size <= max_bytes


def select_format(
    formats: tuple[MediaFormat, ...],
    *,
    max_height: int,
    max_bytes: int,
    duration_seconds: float | None = None,
) -> FormatSelection:
    video_formats = [fmt for fmt in formats if fmt.has_video]
    if video_formats and all(fmt.has_drm for fmt in video_formats):
        raise AppError(
            ErrorCode.PRIVATE_OR_RESTRICTED_CONTENT,
            "DRM-protected videos are not supported.",
        )

    videos = sorted(
        (fmt for fmt in formats if _eligible_video(fmt, max_height)),
        key=lambda fmt: _video_sort_key(fmt, duration_seconds),
        reverse=True,
    )
    if not videos:
        above_ceiling = sorted(
            (
                fmt
                for fmt in formats
                if fmt.has_video
                and not fmt.has_drm
                and _quality_height(fmt) is not None
                and _safe_format_id(fmt.format_id) is not None
            ),
            key=lambda fmt: (
                _quality_height(fmt) or 0,
                fmt.tbr or 0.0,
                _estimated_size(fmt, duration_seconds) or 0,
            ),
        )
        for fmt in above_ceiling:
            if _fits(_estimated_size(fmt, duration_seconds), max_bytes):
                videos = [fmt]
                break
        if not videos:
            if above_ceiling:
                raise AppError(
                    ErrorCode.FILE_TOO_LARGE,
                    "This video is too large to deliver on Telegram.",
                )
            raise AppError(
                ErrorCode.UNSUPPORTED_CONTENT,
                "No downloadable video quality was found for this link.",
            )

    combined_candidates = [fmt for fmt in videos if fmt.has_audio]
    audio_candidates = sorted(
        (fmt for fmt in formats if fmt.has_audio and not fmt.has_video and not fmt.has_drm),
        key=lambda fmt: _audio_sort_key(fmt, duration_seconds),
        reverse=True,
    )

    combined_choice: MediaFormat | None = None
    for fmt in combined_candidates:
        if _fits(_estimated_size(fmt, duration_seconds), max_bytes):
            combined_choice = fmt
            break

    video_candidates = [fmt for fmt in videos if not fmt.has_audio]
    separate_choice: tuple[MediaFormat, MediaFormat] | None = None
    if audio_candidates:
        for video in video_candidates:
            video_size = _estimated_size(video, duration_seconds)
            for audio in audio_candidates:
                audio_size = _estimated_size(audio, duration_seconds)
                if video_size is None or audio_size is None:
                    total_size = None
                else:
                    total_size = video_size + audio_size
                if _fits(total_size, max_bytes):
                    separate_choice = (video, audio)
                    break
            if separate_choice is not None:
                break

    silent_choice: MediaFormat | None = None
    if not combined_candidates and not audio_candidates and video_candidates:
        silent_choice = video_candidates[0]

    if combined_choice is None and separate_choice is None and silent_choice is None:
        if combined_candidates or (video_candidates and audio_candidates):
            raise AppError(
                ErrorCode.FILE_TOO_LARGE,
                "This video is too large to deliver on Telegram.",
            )
        raise AppError(
            ErrorCode.UNSUPPORTED_CONTENT,
            "No downloadable video quality was found for this link.",
        )

    if combined_choice is not None and (
        separate_choice is None
        or (_quality_height(combined_choice) or 0) >= (_quality_height(separate_choice[0]) or 0)
    ):
        video_id = _safe_format_id(combined_choice.format_id)
        assert video_id is not None
        return FormatSelection(
            format_spec=video_id,
            video_format_id=video_id,
            audio_format_id=None,
            expected_height=min(_quality_height(combined_choice) or max_height, max_height),
            estimated_bytes=_estimated_size(combined_choice, duration_seconds),
            combined=True,
            fallback_format_spec=f"best[height<={max_height}]/best[width<={max_height}]",
        )

    if separate_choice is None:
        assert silent_choice is not None
        video_id = _safe_format_id(silent_choice.format_id)
        assert video_id is not None
        return FormatSelection(
            format_spec=video_id,
            video_format_id=video_id,
            audio_format_id=None,
            expected_height=min(_quality_height(silent_choice) or max_height, max_height),
            estimated_bytes=_estimated_size(silent_choice, duration_seconds),
            combined=False,
            fallback_format_spec=f"best[height<={max_height}]/best[width<={max_height}]",
        )

    video, audio = separate_choice
    video_id = _safe_format_id(video.format_id)
    audio_id = _safe_format_id(audio.format_id)
    if video_id is None or audio_id is None:
        raise AppError(
            ErrorCode.UNSUPPORTED_CONTENT,
            "No downloadable video quality was found for this link.",
        )
    sizes = [
        _estimated_size(video, duration_seconds),
        _estimated_size(audio, duration_seconds),
    ]
    estimated_size = None if None in sizes else sum(size or 0 for size in sizes)
    return FormatSelection(
        format_spec=f"{video_id}+{audio_id}",
        video_format_id=video_id,
        audio_format_id=audio_id,
        expected_height=min(_quality_height(video) or max_height, max_height),
        estimated_bytes=estimated_size,
        combined=False,
        fallback_format_spec=(
            f"{video_id}+bestaudio/best[height<={max_height}]/best[width<={max_height}]"
        ),
    )
