import asyncio
import os
import signal
from dataclasses import dataclass
from pathlib import Path

from backend.core.errors import AppError, ErrorCode
from backend.media.ffprobe import ProbeResult, probe_media, validate_probe

_MAX_FFMPEG_STDERR_BYTES = 256 * 1024


@dataclass(frozen=True, slots=True)
class PreparedMedia:
    path: Path
    probe: ProbeResult
    mime_type: str


async def _run_ffmpeg(args: list[str], *, timeout_seconds: int) -> None:
    process = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        *args,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    try:
        _, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_seconds)
    except TimeoutError as exc:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await process.wait()
        raise AppError(
            ErrorCode.PROCESSING_TIMEOUT,
            "The video took too long to process. Please try again later.",
        ) from exc
    if process.returncode != 0 or len(stderr) > _MAX_FFMPEG_STDERR_BYTES:
        raise AppError(
            ErrorCode.INTERNAL_ERROR,
            "The video could not be prepared for delivery. Please try again later.",
        )


def _transcode_filter(max_height: int) -> str:
    return (
        "scale="
        f"w='if(gte(iw,ih),-2,trunc(min({max_height},iw)/2)*2)':"
        f"h='if(gte(iw,ih),trunc(min({max_height},ih)/2)*2,-2)'"
    )


async def prepare_media(
    source: Path,
    workspace: Path,
    *,
    max_height: int,
    max_bytes: int,
    max_duration_seconds: int,
    ffmpeg_timeout_seconds: int = 600,
) -> PreparedMedia:
    initial = await probe_media(source)
    if initial.size_bytes > max_bytes:
        raise AppError(
            ErrorCode.FILE_TOO_LARGE,
            "This video is too large to deliver on Telegram.",
        )
    if initial.duration_seconds is not None and initial.duration_seconds > max_duration_seconds:
        raise AppError(
            ErrorCode.DURATION_LIMIT,
            "This video is longer than the supported limit.",
        )

    target = workspace / "output.mp4"
    common = [
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-movflags",
        "+faststart",
        "-map_metadata",
        "-1",
    ]

    if initial.quality_height <= max_height and initial.video_codec == "h264":
        if initial.audio_codec in (None, "aac"):
            args = ["-i", str(source), *common, "-c", "copy", str(target)]
        else:
            args = [
                "-i",
                str(source),
                *common,
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                str(target),
            ]
    else:
        args = [
            "-i",
            str(source),
            *common,
            "-vf",
            _transcode_filter(max_height),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            str(target),
        ]

    await _run_ffmpeg(args, timeout_seconds=ffmpeg_timeout_seconds)
    if not target.is_file() or target.stat().st_size <= 0:
        raise AppError(
            ErrorCode.INTERNAL_ERROR,
            "The video could not be prepared for delivery. Please try again later.",
        )

    result = await probe_media(target)
    validate_probe(
        result,
        max_height=max_height,
        max_bytes=max_bytes,
        max_duration_seconds=max_duration_seconds,
    )
    return PreparedMedia(path=target, probe=result, mime_type="video/mp4")
