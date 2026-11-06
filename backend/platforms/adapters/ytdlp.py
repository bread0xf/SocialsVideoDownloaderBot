import asyncio
import json
import os
import signal
from pathlib import Path

from backend.core.errors import AppError, ErrorCode
from backend.platforms.adapters.base import FormatSelection, MediaFormat, MediaMetadata
from backend.platforms.urls import NormalizedURL

_VIDEO_SUFFIXES = frozenset({".mp4", ".mkv", ".webm", ".mov"})
_MAX_STDOUT_BYTES = 8 * 1024 * 1024
_MAX_STDERR_BYTES = 256 * 1024


def _int_or_none(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


def _float_or_none(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def _str_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _classify_failure(stderr: str) -> AppError:
    lowered = stderr.lower()
    if any(
        marker in lowered
        for marker in (
            "private",
            "login required",
            "sign in",
            "cookies",
            "requested content is not available",
            "age-restricted",
        )
    ):
        return AppError(
            ErrorCode.PRIVATE_OR_RESTRICTED_CONTENT,
            "That content is private or restricted. Only public videos are supported.",
        )
    if "unsupported url" in lowered:
        return AppError(
            ErrorCode.UNSUPPORTED_CONTENT,
            "That link type is not supported. Send a public individual video link.",
        )
    if "live event" in lowered or "is live" in lowered or "live stream" in lowered:
        return AppError(
            ErrorCode.UNSUPPORTED_CONTENT,
            "Live streams are not supported.",
        )
    if "max-filesize" in lowered or "file is larger than" in lowered:
        return AppError(
            ErrorCode.FILE_TOO_LARGE,
            "This video is too large to deliver on Telegram.",
        )
    if any(
        marker in lowered
        for marker in (
            "unable to download",
            "video unavailable",
            "not available",
            "404",
            "not found",
            "http error 410",
        )
    ):
        return AppError(
            ErrorCode.SOURCE_UNAVAILABLE,
            "That video is not available. It may have been removed or made private.",
        )
    return AppError(
        ErrorCode.TEMPORARY_FAILURE,
        "The video could not be processed right now. Please try again later.",
    )


def _collect_output_file(workspace: Path, max_bytes: int) -> Path:
    resolved_workspace = workspace.resolve()
    candidates: list[Path] = []
    for path in workspace.iterdir():
        if not path.is_file() or path.suffix.lower() not in _VIDEO_SUFFIXES:
            continue
        resolved = path.resolve()
        if not resolved.is_relative_to(resolved_workspace):
            continue
        if resolved.stat().st_size <= 0:
            continue
        candidates.append(resolved)
    if len(candidates) != 1:
        raise AppError(
            ErrorCode.INTERNAL_ERROR,
            "The video could not be processed right now. Please try again later.",
        )
    result = candidates[0]
    if result.stat().st_size > max_bytes:
        result.unlink(missing_ok=True)
        raise AppError(
            ErrorCode.FILE_TOO_LARGE,
            "This video is too large to deliver on Telegram.",
        )
    return result


class YtDlpAdapter:
    def __init__(
        self,
        *,
        extractor_timeout_seconds: int,
        socket_timeout_seconds: int = 15,
        max_output_bytes: int = _MAX_STDOUT_BYTES,
    ) -> None:
        self._timeout = extractor_timeout_seconds
        self._socket_timeout = socket_timeout_seconds
        self._max_output_bytes = max_output_bytes

    def _environment(self, workspace: Path) -> dict[str, str]:
        env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": str(workspace),
            "TMPDIR": str(workspace),
            "XDG_CACHE_HOME": str(workspace / ".cache"),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PYTHONUNBUFFERED": "1",
            "NO_COLOR": "1",
        }
        for key in ("SSL_CERT_FILE", "SSL_CERT_DIR", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY"):
            value = os.environ.get(key)
            if value:
                env[key] = value
        return env

    async def _run(self, args: list[str], *, workspace: Path) -> str:
        (workspace / ".cache").mkdir(parents=True, exist_ok=True)
        process = await asyncio.create_subprocess_exec(
            "yt-dlp",
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=workspace,
            env=self._environment(workspace),
            start_new_session=True,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=self._timeout)
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

        if len(stdout) > self._max_output_bytes or len(stderr) > _MAX_STDERR_BYTES:
            raise AppError(
                ErrorCode.INTERNAL_ERROR,
                "The video could not be processed right now. Please try again later.",
            )
        if process.returncode != 0:
            raise _classify_failure(stderr.decode("utf-8", errors="replace"))
        return stdout.decode("utf-8", errors="replace")

    def _common_args(self) -> list[str]:
        return [
            "--ignore-config",
            "--no-cache-dir",
            "--no-playlist",
            "--no-warnings",
            "--no-progress",
            "--no-mtime",
            "--no-write-thumbnail",
            "--no-write-info-json",
            "--socket-timeout",
            str(self._socket_timeout),
            "--retries",
            "2",
        ]

    async def inspect(self, url: NormalizedURL, workspace: Path) -> MediaMetadata:
        args = [
            *self._common_args(),
            "--skip-download",
            "--dump-single-json",
            "--",
            url.url,
        ]
        output = await self._run(args, workspace=workspace)
        try:
            data = json.loads(output)
        except json.JSONDecodeError as exc:
            raise AppError(
                ErrorCode.SOURCE_UNAVAILABLE,
                "That video's details could not be read. Please try again later.",
            ) from exc
        if not isinstance(data, dict):
            raise AppError(
                ErrorCode.UNSUPPORTED_CONTENT,
                "That link type is not supported. Send a public individual video link.",
            )
        if data.get("_type") == "playlist" or isinstance(data.get("entries"), list):
            raise AppError(
                ErrorCode.UNSUPPORTED_CONTENT,
                "Playlists, channels and multi-video links are not supported.",
            )

        live_status = data.get("live_status")
        is_live = bool(data.get("is_live")) or live_status in {"is_live", "is_upcoming"}
        formats: list[MediaFormat] = []
        raw_formats = data.get("formats")
        if isinstance(raw_formats, list):
            for raw in raw_formats:
                if not isinstance(raw, dict):
                    continue
                format_id = _str_or_none(raw.get("format_id"))
                if format_id is None:
                    continue
                formats.append(
                    MediaFormat(
                        format_id=format_id,
                        ext=_str_or_none(raw.get("ext")),
                        width=_int_or_none(raw.get("width")),
                        height=_int_or_none(raw.get("height")),
                        vcodec=_str_or_none(raw.get("vcodec")),
                        acodec=_str_or_none(raw.get("acodec")),
                        filesize=_int_or_none(raw.get("filesize"))
                        or _int_or_none(raw.get("filesize_approx")),
                        tbr=_float_or_none(raw.get("tbr")),
                        protocol=_str_or_none(raw.get("protocol")),
                    )
                )

        return MediaMetadata(
            title=_str_or_none(data.get("title")),
            duration_seconds=_float_or_none(data.get("duration")),
            is_live=is_live,
            webpage_url=_str_or_none(data.get("webpage_url")),
            extractor=_str_or_none(data.get("extractor")),
            formats=tuple(formats),
        )

    async def download(
        self,
        url: NormalizedURL,
        selection: FormatSelection,
        workspace: Path,
        *,
        max_bytes: int,
    ) -> Path:
        args = [
            *self._common_args(),
            "--max-filesize",
            str(max_bytes),
            "--format",
            selection.format_spec,
            "--merge-output-format",
            "mp4",
            "--paths",
            str(workspace),
            "--output",
            "download.%(ext)s",
            "--",
            url.url,
        ]
        await self._run(args, workspace=workspace)
        return await asyncio.to_thread(_collect_output_file, workspace, max_bytes)
