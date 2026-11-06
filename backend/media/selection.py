import re

from backend.core.errors import AppError, ErrorCode
from backend.platforms.adapters.base import FormatSelection, MediaFormat

_SAFE_FORMAT_ID = re.compile(r"^[A-Za-z0-9_.:=@-]+$")
_H264_CODECS = frozenset({"h264", "avc1", "avc1.4d401f", "avc1.64001f"})
_AAC_CODECS = frozenset({"aac", "mp4a", "mp4a.40.2"})


def _safe_format_id(value: str | None) -> str | None:
    if not value or not _SAFE_FORMAT_ID.match(value):
        return None
    return value


def _known_size(fmt: MediaFormat) -> int | None:
    if fmt.filesize is not None and fmt.filesize >= 0:
        return fmt.filesize
    return None


def _codec_score(fmt: MediaFormat) -> int:
    score = 0
    if fmt.ext == "mp4":
        score += 1
    if fmt.vcodec in _H264_CODECS:
        score += 4
    if fmt.acodec in _AAC_CODECS:
        score += 2
    if fmt.protocol in {None, "https", "http"}:
        score += 1
    return score


def _eligible_video(fmt: MediaFormat, max_height: int) -> bool:
    if not fmt.has_video or fmt.height is None:
        return False
    if fmt.height <= 0 or fmt.height > max_height:
        return False
    if not fmt.width or fmt.width <= 0:
        return False
    return _safe_format_id(fmt.format_id) is not None


def _video_sort_key(fmt: MediaFormat) -> tuple[int, int, int, float]:
    return (fmt.height or 0, _codec_score(fmt), _known_size(fmt) or 0, fmt.tbr or 0.0)


def _audio_sort_key(fmt: MediaFormat) -> tuple[int, float, int]:
    return (
        1 if fmt.acodec in _AAC_CODECS else 0,
        fmt.tbr or 0.0,
        _known_size(fmt) or 0,
    )


def _fits(size: int | None, *limits: int) -> bool:
    return size is None or size <= min(limits)


def select_format(
    formats: tuple[MediaFormat, ...],
    *,
    max_height: int,
    max_bytes: int,
) -> FormatSelection:
    videos = sorted(
        (fmt for fmt in formats if _eligible_video(fmt, max_height)),
        key=_video_sort_key,
        reverse=True,
    )
    if not videos:
        raise AppError(
            ErrorCode.UNSUPPORTED_CONTENT,
            "No downloadable video quality was found for this link.",
        )

    combined_candidates = [fmt for fmt in videos if fmt.has_audio]
    audio_candidates = sorted(
        (fmt for fmt in formats if fmt.has_audio and not fmt.has_video),
        key=_audio_sort_key,
        reverse=True,
    )

    combined_choice: MediaFormat | None = None
    for fmt in combined_candidates:
        if _fits(_known_size(fmt), max_bytes):
            combined_choice = fmt
            break

    video_candidates = [fmt for fmt in videos if not fmt.has_audio]
    separate_choice: tuple[MediaFormat, MediaFormat] | None = None
    best_audio = audio_candidates[0] if audio_candidates else None
    if video_candidates and best_audio is not None:
        audio_size = _known_size(best_audio) or 0
        for video in video_candidates:
            video_size = _known_size(video)
            if video_size is None or video_size + audio_size <= max_bytes:
                separate_choice = (video, best_audio)
                break

    if combined_choice is None and separate_choice is None:
        if combined_candidates or (video_candidates and best_audio is not None):
            raise AppError(
                ErrorCode.FILE_TOO_LARGE,
                "This video is too large to deliver on Telegram.",
            )
        raise AppError(
            ErrorCode.UNSUPPORTED_CONTENT,
            "No downloadable video quality was found for this link.",
        )

    if combined_choice is not None and (
        separate_choice is None or (combined_choice.height or 0) >= (separate_choice[0].height or 0)
    ):
        video_id = _safe_format_id(combined_choice.format_id)
        assert video_id is not None
        return FormatSelection(
            format_spec=video_id,
            video_format_id=video_id,
            audio_format_id=None,
            expected_height=combined_choice.height,
            estimated_bytes=_known_size(combined_choice),
            combined=True,
        )

    assert separate_choice is not None
    video, audio = separate_choice
    video_id = _safe_format_id(video.format_id)
    audio_id = _safe_format_id(audio.format_id)
    if video_id is None or audio_id is None:
        raise AppError(
            ErrorCode.UNSUPPORTED_CONTENT,
            "No downloadable video quality was found for this link.",
        )
    sizes = [_known_size(video), _known_size(audio)]
    estimated_size = None if None in sizes else sum(size or 0 for size in sizes)
    return FormatSelection(
        format_spec=f"{video_id}+{audio_id}",
        video_format_id=video_id,
        audio_format_id=audio_id,
        expected_height=video.height,
        estimated_bytes=estimated_size,
        combined=False,
    )
