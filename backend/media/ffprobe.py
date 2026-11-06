import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

from backend.core.errors import AppError, ErrorCode

_MAX_PROBE_OUTPUT_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class ProbeResult:
    duration_seconds: float | None
    width: int
    height: int
    video_codec: str | None
    audio_codec: str | None
    format_name: str | None
    size_bytes: int

    @property
    def quality_height(self) -> int:
        return min(self.width, self.height)


def _as_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _as_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


async def probe_media(path: Path, *, timeout_seconds: int = 30) -> ProbeResult:
    process = await asyncio.create_subprocess_exec(
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=timeout_seconds)
    except TimeoutError as exc:
        process.kill()
        await process.wait()
        raise AppError(
            ErrorCode.PROCESSING_TIMEOUT,
            "The video took too long to verify. Please try again later.",
        ) from exc
    if process.returncode != 0 or len(stdout) > _MAX_PROBE_OUTPUT_BYTES:
        raise AppError(
            ErrorCode.UNSUPPORTED_CONTENT,
            "The downloaded file is not a supported video.",
        )
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise AppError(
            ErrorCode.UNSUPPORTED_CONTENT,
            "The downloaded file is not a supported video.",
        ) from exc
    if not isinstance(data, dict):
        raise AppError(
            ErrorCode.UNSUPPORTED_CONTENT,
            "The downloaded file is not a supported video.",
        )

    raw_streams = data.get("streams")
    streams = raw_streams if isinstance(raw_streams, list) else []
    video_stream: dict[str, object] | None = None
    audio_codec: str | None = None
    for stream in streams:
        if not isinstance(stream, dict):
            continue
        codec_type = stream.get("codec_type")
        disposition = stream.get("disposition")
        is_attached_picture = isinstance(disposition, dict) and disposition.get("attached_pic") == 1
        if codec_type == "video" and not is_attached_picture:
            if video_stream is None:
                video_stream = stream
        elif codec_type == "audio" and audio_codec is None:
            codec = stream.get("codec_name")
            audio_codec = codec if isinstance(codec, str) else None
    if video_stream is None:
        raise AppError(
            ErrorCode.UNSUPPORTED_CONTENT,
            "The downloaded file does not contain a video.",
        )

    width = _as_int(video_stream.get("width"))
    height = _as_int(video_stream.get("height"))
    if not width or not height or width <= 0 or height <= 0:
        raise AppError(
            ErrorCode.UNSUPPORTED_CONTENT,
            "The downloaded video has invalid dimensions.",
        )

    raw_format = data.get("format")
    format_data = raw_format if isinstance(raw_format, dict) else {}
    duration = _as_float(format_data.get("duration")) or _as_float(video_stream.get("duration"))
    format_name = format_data.get("format_name")
    video_codec = video_stream.get("codec_name")

    stat_result = await asyncio.to_thread(path.stat)
    return ProbeResult(
        duration_seconds=duration,
        width=width,
        height=height,
        video_codec=video_codec if isinstance(video_codec, str) else None,
        audio_codec=audio_codec,
        format_name=format_name if isinstance(format_name, str) else None,
        size_bytes=stat_result.st_size,
    )


def validate_probe(
    probe: ProbeResult,
    *,
    max_height: int,
    max_bytes: int,
    max_duration_seconds: int,
) -> None:
    if probe.size_bytes > max_bytes:
        raise AppError(
            ErrorCode.FILE_TOO_LARGE,
            "This video is too large to deliver on Telegram.",
        )
    if probe.duration_seconds is not None and probe.duration_seconds > max_duration_seconds:
        raise AppError(
            ErrorCode.DURATION_LIMIT,
            "This video is longer than the supported limit.",
        )
    if probe.quality_height > max_height:
        raise AppError(
            ErrorCode.UNSUPPORTED_CONTENT,
            "This video does not provide a quality allowed on your plan.",
        )
