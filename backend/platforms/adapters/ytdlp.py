import asyncio
import json
import os
import signal
from pathlib import Path

from backend.core.errors import AppError, ErrorCode
from backend.platforms.adapters.base import FormatSelection, MediaFormat, MediaMetadata
from backend.platforms.urls import NormalizedURL, validate_extracted_url

_VIDEO_SUFFIXES = frozenset({".mp4", ".mkv", ".webm", ".mov"})
_MAX_STDOUT_BYTES = 8 * 1024 * 1024
_MAX_STDERR_BYTES = 256 * 1024

_RESTRICTED_AVAILABILITY = frozenset({"private", "premium_only", "subscriber_only", "needs_auth"})


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


def _positive_int_or_none(value: object) -> int | None:
    parsed = _int_or_none(value)
    return parsed if parsed is not None and parsed > 0 else None


def classify_failure(stderr: str) -> AppError:
    lowered = stderr.lower()
    if any(
        marker in lowered
        for marker in (
            "private video",
            "this video is private",
            "login required",
            "sign in to confirm",
            "sign in to view",
            "requires authentication",
            "cookies",
            "age-restricted",
            "age restricted",
            "members-only",
            "members only",
            "join this channel",
            "subscriber-only",
            "subscriber only",
            "requested content is not available",
            "not available in your country",
            "geo-restricted",
            "blocked in your country",
        )
    ):
        return AppError(
            ErrorCode.PRIVATE_OR_RESTRICTED_CONTENT,
            "That content is private or restricted. Only public videos are supported.",
        )
    if any(
        marker in lowered
        for marker in ("live event", "is live", "live stream", "premieres in", "will begin in")
    ):
        return AppError(
            ErrorCode.UNSUPPORTED_CONTENT,
            "Live streams are not supported.",
        )
    if any(
        marker in lowered
        for marker in ("max-filesize", "file is larger than", "exceeds the maximum")
    ):
        return AppError(
            ErrorCode.FILE_TOO_LARGE,
            "This video is too large to deliver on Telegram.",
        )
    if any(
        marker in lowered
        for marker in (
            "unsupported url",
            "no video formats found",
            "no formats found",
            "requested format is not available",
            "no suitable format",
        )
    ):
        return AppError(
            ErrorCode.UNSUPPORTED_CONTENT,
            "That link type is not supported. Send a public individual video link.",
        )
    if any(
        marker in lowered
        for marker in (
            "video unavailable",
            "this video is unavailable",
            "unable to download",
            "http error 404",
            "http error 410",
            "not found",
            "no longer available",
            "has been removed",
            "copyright",
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


def _parse_format(raw: dict[str, object]) -> MediaFormat | None:
    format_id = _str_or_none(raw.get("format_id"))
    if format_id is None:
        return None
    return MediaFormat(
        format_id=format_id,
        ext=_str_or_none(raw.get("ext")),
        width=_int_or_none(raw.get("width")),
        height=_int_or_none(raw.get("height")),
        vcodec=_str_or_none(raw.get("vcodec")),
        acodec=_str_or_none(raw.get("acodec")),
        filesize=_positive_int_or_none(raw.get("filesize"))
        or _positive_int_or_none(raw.get("filesize_approx")),
        tbr=_float_or_none(raw.get("tbr")),
        protocol=_str_or_none(raw.get("protocol")),
        has_drm=bool(raw.get("has_drm")),
    )


def _single_video_entry(data: dict[str, object]) -> dict[str, object]:
    entries = data.get("entries")
    if not isinstance(entries, list):
        raise AppError(
            ErrorCode.UNSUPPORTED_CONTENT,
            "Playlists, channels and multi-video links are not supported.",
        )
    video_entries = [
        entry
        for entry in entries
        if isinstance(entry, dict) and entry.get("formats") and not bool(entry.get("is_live"))
    ]
    if len(video_entries) != 1:
        raise AppError(
            ErrorCode.UNSUPPORTED_CONTENT,
            "Playlists, channels and multi-video links are not supported.",
        )
    entry = dict(video_entries[0])
    for key in ("availability", "duration", "extractor", "extractor_key", "webpage_url"):
        if key not in entry and key in data:
            entry[key] = data[key]
    return entry


def parse_metadata(data: dict[str, object]) -> MediaMetadata:
    if data.get("_type") == "playlist" or isinstance(data.get("entries"), list):
        data = _single_video_entry(data)

    availability = _str_or_none(data.get("availability"))
    if availability in _RESTRICTED_AVAILABILITY:
        raise AppError(
            ErrorCode.PRIVATE_OR_RESTRICTED_CONTENT,
            "That content is private or restricted. Only public videos are supported.",
        )
    if bool(data.get("_has_drm")):
        raise AppError(
            ErrorCode.PRIVATE_OR_RESTRICTED_CONTENT,
            "DRM-protected videos are not supported.",
        )

    live_status = data.get("live_status")
    is_live = bool(data.get("is_live")) or live_status in {"is_live", "is_upcoming"}

    formats: list[MediaFormat] = []
    raw_formats = data.get("formats")
    if isinstance(raw_formats, list):
        for raw in raw_formats:
            if not isinstance(raw, dict):
                continue
            parsed = _parse_format(raw)
            if parsed is not None:
                formats.append(parsed)

    return MediaMetadata(
        title=_str_or_none(data.get("title")),
        duration_seconds=_float_or_none(data.get("duration")),
        is_live=is_live,
        webpage_url=_str_or_none(data.get("webpage_url")) or _str_or_none(data.get("original_url")),
        extractor=_str_or_none(data.get("extractor_key")) or _str_or_none(data.get("extractor")),
        formats=tuple(formats),
        availability=availability,
    )


class YtDlpAdapter:
    def __init__(
        self,
        *,
        metadata_timeout_seconds: int,
        download_timeout_seconds: int,
        socket_timeout_seconds: int = 15,
        max_output_bytes: int = _MAX_STDOUT_BYTES,
    ) -> None:
        self._metadata_timeout = metadata_timeout_seconds
        self._download_timeout = download_timeout_seconds
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

    async def _run(self, args: list[str], *, workspace: Path, timeout_seconds: int) -> str:
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
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_seconds)
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
            raise classify_failure(stderr.decode("utf-8", errors="replace"))
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
            "--fragment-retries",
            "2",
            "--extractor-retries",
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
        output = await self._run(
            args,
            workspace=workspace,
            timeout_seconds=self._metadata_timeout,
        )
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
        metadata = parse_metadata(data)
        validate_extracted_url(url, metadata.webpage_url)
        return metadata

    async def download(
        self,
        url: NormalizedURL,
        selection: FormatSelection,
        workspace: Path,
        *,
        max_bytes: int,
    ) -> Path:
        format_spec = selection.format_spec
        if selection.fallback_format_spec:
            format_spec = f"{format_spec}/{selection.fallback_format_spec}"
        args = [
            *self._common_args(),
            "--max-filesize",
            str(max_bytes),
            "--format",
            format_spec,
            "--merge-output-format",
            "mp4",
            "--paths",
            str(workspace),
            "--output",
            "download.%(ext)s",
            "--",
            url.url,
        ]
        await self._run(
            args,
            workspace=workspace,
            timeout_seconds=self._download_timeout,
        )
        return await asyncio.to_thread(_collect_output_file, workspace, max_bytes)
