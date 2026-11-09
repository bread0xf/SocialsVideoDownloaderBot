#!/usr/bin/env python3
"""Friendly workbench CLI for the extraction and download engine."""

from __future__ import annotations

import argparse
import asyncio
import re
import shutil
import sys
import tempfile
import time
import traceback
import uuid
from dataclasses import dataclass
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.core.config import Settings, get_settings
from backend.core.errors import AppError, ErrorCode
from backend.media.processing import PreparedMedia, prepare_media
from backend.media.selection import select_format
from backend.platforms.adapters.base import FormatSelection, MediaFormat, MediaMetadata
from backend.platforms.adapters.ytdlp import YtDlpAdapter
from backend.platforms.urls import NormalizedURL, normalize_url, resolve_public_addresses

WORKBENCH_ROOT = Path(__file__).resolve().parents[1] / "workbench"
DOWNLOADS_ROOT = WORKBENCH_ROOT / "downloads"

_SIZE_UNITS = {
    "": 1,
    "b": 1,
    "k": 1024,
    "kb": 1024,
    "kib": 1024,
    "m": 1024**2,
    "mb": 1024**2,
    "mib": 1024**2,
    "g": 1024**3,
    "gb": 1024**3,
    "gib": 1024**3,
}

_DURATION_UNITS = {"": 1, "s": 1, "m": 60, "h": 3600}


@dataclass(frozen=True, slots=True)
class EngineOptions:
    max_height: int
    max_bytes: int
    max_duration: int
    metadata_timeout: int
    download_timeout: int
    ffmpeg_timeout: int


@dataclass(frozen=True, slots=True)
class Inspection:
    normalized: NormalizedURL
    metadata: MediaMetadata
    selection: FormatSelection | None
    selection_error: str | None


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"{value!r} is not an integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return parsed


def _parse_byte_size(value: str) -> int:
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([a-zA-Z]*)\s*", value)
    if match is None:
        raise argparse.ArgumentTypeError(f"{value!r} is not a size like 48MiB or 500MB")
    number, unit = match.groups()
    multiplier = _SIZE_UNITS.get(unit.lower())
    if multiplier is None:
        raise argparse.ArgumentTypeError(f"unknown size unit {unit!r}")
    parsed = int(float(number) * multiplier)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("size must be greater than zero")
    return parsed


def _parse_duration(value: str) -> int:
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([smhSMH]?)\s*", value)
    if match is None:
        raise argparse.ArgumentTypeError(f"{value!r} is not a duration like 600, 10m or 1h")
    number, unit = match.groups()
    multiplier = _DURATION_UNITS.get(unit.lower())
    if multiplier is None:
        raise argparse.ArgumentTypeError(f"unknown duration unit {unit!r}")
    parsed = int(float(number) * multiplier)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("duration must be greater than zero")
    return parsed


def _human_bytes(value: int | None) -> str:
    if value is None:
        return "unknown"
    if value < 1024:
        return f"{value} B"
    amount = float(value)
    for unit in ("KiB", "MiB", "GiB", "TiB"):
        amount /= 1024
        if amount < 1024:
            return f"{amount:.1f} {unit}"
    return f"{amount:.1f} PiB"


def _human_duration(value: float | None) -> str:
    if value is None:
        return "unknown"
    total = int(value)
    if total < 60:
        return f"{total}s"
    minutes, seconds = divmod(total, 60)
    if minutes < 60:
        return f"{minutes}m {seconds}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m {seconds}s"


def _dimensions(fmt: MediaFormat) -> str:
    if fmt.width and fmt.height:
        return f"{fmt.width}x{fmt.height}"
    return "-"


def _codec(value: str | None) -> str:
    return value if value else "-"


def _format_flags(fmt: MediaFormat) -> str:
    flags: list[str] = []
    if fmt.has_video and fmt.has_audio:
        flags.append("A/V")
    elif fmt.has_video:
        flags.append("video")
    elif fmt.has_audio:
        flags.append("audio")
    if fmt.has_drm:
        flags.append("DRM")
    return ",".join(flags) or "-"


def _format_row(fmt: MediaFormat) -> str:
    return (
        f"{fmt.format_id:<16} {fmt.ext or '-':<6} {_dimensions(fmt):<12} "
        f"{_codec(fmt.vcodec):<16} {_codec(fmt.acodec):<14} "
        f"{_human_bytes(fmt.filesize):>10} {fmt.protocol or '-':<12} {_format_flags(fmt)}"
    )


def _print_format_table(metadata: MediaMetadata) -> None:
    visible = [fmt for fmt in metadata.formats if fmt.has_video or fmt.has_audio]
    if not visible:
        print("No video or audio formats reported.")
        return
    visible.sort(key=lambda fmt: (fmt.height or 0, fmt.tbr or 0), reverse=True)
    print(
        f"{'ID':<16} {'EXT':<6} {'DIMENSIONS':<12} {'VIDEO':<16} "
        f"{'AUDIO':<14} {'SIZE':>10} {'PROTO':<12} FLAGS"
    )
    for fmt in visible:
        print(_format_row(fmt))


def _print_selection(selection: FormatSelection) -> None:
    kind = "combined" if selection.combined else "separate or silent"
    print(f"Selected format : {selection.format_spec} ({kind})")
    print(f"Expected quality: {selection.expected_height}p")
    print(f"Estimated size  : {_human_bytes(selection.estimated_bytes)}")
    if selection.fallback_format_spec:
        print(f"Fallback format : {selection.fallback_format_spec}")


def _print_inspection(inspection: Inspection, options: EngineOptions) -> None:
    metadata = inspection.metadata
    print()
    print(f"Canonical URL : {inspection.normalized.url}")
    print(
        f"Platform      : {inspection.normalized.platform} / {inspection.normalized.content_type}"
    )
    print(f"Title         : {metadata.title or '(unknown)'}")
    print(f"Duration      : {_human_duration(metadata.duration_seconds)}")
    print(f"Extractor     : {metadata.extractor or '(unknown)'}")
    print(f"Availability  : {metadata.availability or 'public'}")
    if metadata.duration_seconds is not None and metadata.duration_seconds > options.max_duration:
        print(
            "Warning       : duration exceeds the current limit "
            f"({_human_duration(options.max_duration)}); download will be rejected."
        )
    print()
    print("Available formats")
    print("-" * 112)
    _print_format_table(metadata)
    print("-" * 112)
    if inspection.selection is None:
        print(f"No format selected: {inspection.selection_error or 'no eligible format'}")
    else:
        _print_selection(inspection.selection)


def _file_size(path: Path) -> int:
    return path.stat().st_size


def _expand_path(path: Path) -> Path:
    return path.expanduser()


def _make_work_dir() -> Path:
    DOWNLOADS_ROOT.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="job-", dir=DOWNLOADS_ROOT))


def _remove_work_dir(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def _default_output_path(normalized: NormalizedURL) -> Path:
    safe_id = re.sub(r"[^A-Za-z0-9._-]+", "_", normalized.source_id).strip("._")
    safe_id = safe_id[:64] or "video"
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return DOWNLOADS_ROOT / f"{normalized.platform}-{safe_id}-{stamp}.mp4"


def _publish_output(source: Path, target: Path, *, force: bool) -> None:
    if target.exists() and target.is_dir():
        raise AppError(ErrorCode.INTERNAL_ERROR, "The output path is a directory.")
    if target.exists() and not force:
        raise AppError(
            ErrorCode.INTERNAL_ERROR,
            "The output file already exists. Use --force to overwrite it.",
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.parent / f".{target.name}.{uuid.uuid4().hex}.tmp"
    try:
        shutil.copy2(source, temp)
        temp.replace(target)
    finally:
        temp.unlink(missing_ok=True)


class EngineWorkbench:
    def __init__(self, options: EngineOptions, *, verbose: bool = False) -> None:
        self.options = options
        self.verbose = verbose
        self.adapter = YtDlpAdapter(
            metadata_timeout_seconds=options.metadata_timeout,
            download_timeout_seconds=options.download_timeout,
        )

    async def inspect(self, raw_url: str) -> Inspection:
        normalized = normalize_url(raw_url)
        print(f"Resolved link: {normalized.url}")
        print(f"Platform    : {normalized.platform} / {normalized.content_type}")
        print("Checking DNS and extracting metadata...")
        await resolve_public_addresses(normalized.host)
        with tempfile.TemporaryDirectory(prefix="svdb-inspect-") as directory:
            metadata = await self.adapter.inspect(normalized, Path(directory))
        if metadata.is_live:
            raise AppError(ErrorCode.UNSUPPORTED_CONTENT, "Live streams are not supported.")

        selection: FormatSelection | None = None
        selection_error: str | None = None
        try:
            selection = select_format(
                metadata.formats,
                max_height=self.options.max_height,
                max_bytes=self.options.max_bytes,
                duration_seconds=metadata.duration_seconds,
            )
        except AppError as exc:
            selection_error = f"[{exc.code.value}] {exc.safe_message}"
        return Inspection(
            normalized=normalized,
            metadata=metadata,
            selection=selection,
            selection_error=selection_error,
        )

    async def download(
        self,
        inspection: Inspection,
        *,
        output: Path | None = None,
        force: bool = False,
    ) -> Path:
        selection = inspection.selection
        if selection is None:
            raise AppError(
                ErrorCode.UNSUPPORTED_CONTENT,
                inspection.selection_error or "No downloadable format was selected.",
            )
        duration = inspection.metadata.duration_seconds
        if duration is not None and duration > self.options.max_duration:
            raise AppError(
                ErrorCode.DURATION_LIMIT,
                "This video is longer than the current workbench duration limit.",
            )

        work_dir = await asyncio.to_thread(_make_work_dir)
        try:
            print()
            print("Downloading source...")
            source = await self.adapter.download(
                inspection.normalized,
                selection,
                work_dir,
                max_bytes=self.options.max_bytes,
            )
            source_size = await asyncio.to_thread(_file_size, source)
            print(f"Downloaded     : {_human_bytes(source_size)}")
            print("Preparing output with FFmpeg...")
            prepared = await prepare_media(
                source,
                work_dir,
                max_height=self.options.max_height,
                max_bytes=self.options.max_bytes,
                max_duration_seconds=self.options.max_duration,
                ffmpeg_timeout_seconds=self.options.ffmpeg_timeout,
            )
            if output is not None:
                target = await asyncio.to_thread(_expand_path, output)
            else:
                target = _default_output_path(inspection.normalized)
            await asyncio.to_thread(_publish_output, prepared.path, target, force=force)
            self._print_prepared(target, prepared)
            return target
        finally:
            await asyncio.to_thread(_remove_work_dir, work_dir)

    def _print_prepared(self, target: Path, prepared: PreparedMedia) -> None:
        probe = prepared.probe
        print()
        print("Done.")
        print(f"Output    : {target}")
        print(f"Size      : {_human_bytes(probe.size_bytes)}")
        print(f"Quality   : {probe.width}x{probe.height} (shorter side {probe.quality_height}p)")
        print(f"Duration  : {_human_duration(probe.duration_seconds)}")
        print(f"Codecs    : {probe.video_codec or '-'} / {probe.audio_codec or '-'}")
        print(f"MIME type : {prepared.mime_type}")


def _print_app_error(exc: AppError, *, verbose: bool) -> None:
    print()
    print(f"Error [{exc.code.value}]: {exc.safe_message}")
    if verbose:
        traceback.print_exc()


def _print_unexpected_error(exc: Exception, *, verbose: bool) -> None:
    print()
    print(f"Unexpected error: {exc}")
    if verbose:
        traceback.print_exc()


def _banner(options: EngineOptions) -> None:
    print("=" * 72)
    print("SocialsVideoDownloaderBot - Engine Workbench")
    print("=" * 72)
    print(
        f"Limits: {options.max_height}p max, {_human_bytes(options.max_bytes)} max, "
        f"{_human_duration(options.max_duration)} max"
    )
    print("No Telegram, database, Redis, quota or billing. Outputs: workbench/downloads/")
    print()


async def _prompt(message: str) -> str:
    return (await asyncio.to_thread(input, message)).strip()


async def _interactive(workbench: EngineWorkbench, options: EngineOptions) -> int:
    _banner(options)
    print("Paste a supported public video link. Press Ctrl+C to exit.")
    while True:
        raw_url = await _prompt("\nLink (or 'q' to quit): ")
        if raw_url.lower() in {"q", "quit", "exit"}:
            print("Bye.")
            return 0
        if not raw_url:
            continue
        try:
            inspection = await workbench.inspect(raw_url)
        except AppError as exc:
            _print_app_error(exc, verbose=workbench.verbose)
            continue
        except Exception as exc:
            _print_unexpected_error(exc, verbose=workbench.verbose)
            continue

        _print_inspection(inspection, options)
        if inspection.selection is None:
            print("Adjust the limits with --max-height, --max-bytes or --max-duration.")
            continue

        answer = await _prompt("\nDownload this video? [y/N]: ")
        if answer.lower() not in {"y", "yes"}:
            continue
        raw_output = await _prompt("Output path (blank for automatic): ")
        answer_force = await _prompt("Overwrite if the file exists? [y/N]: ")
        try:
            await workbench.download(
                inspection,
                output=Path(raw_output) if raw_output else None,
                force=answer_force.lower() in {"y", "yes"},
            )
        except AppError as exc:
            _print_app_error(exc, verbose=workbench.verbose)
        except Exception as exc:
            _print_unexpected_error(exc, verbose=workbench.verbose)


def _build_options(args: argparse.Namespace, settings: Settings) -> EngineOptions:
    return EngineOptions(
        max_height=(
            args.max_height if args.max_height is not None else settings.free_max_resolution_p
        ),
        max_bytes=args.max_bytes if args.max_bytes is not None else settings.max_media_bytes,
        max_duration=(
            args.max_duration
            if args.max_duration is not None
            else settings.max_media_duration_seconds
        ),
        metadata_timeout=(
            args.metadata_timeout
            if args.metadata_timeout is not None
            else settings.extractor_metadata_timeout_seconds
        ),
        download_timeout=(
            args.download_timeout
            if args.download_timeout is not None
            else settings.extractor_download_timeout_seconds
        ),
        ffmpeg_timeout=(
            args.ffmpeg_timeout
            if args.ffmpeg_timeout is not None
            else settings.ffmpeg_timeout_seconds
        ),
    )


def _add_engine_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--max-height",
        type=_positive_int,
        metavar="P",
        help="maximum selected height in pixels (default: free plan ceiling)",
    )
    parser.add_argument(
        "--max-bytes",
        type=_parse_byte_size,
        metavar="SIZE",
        help="maximum source/output size, for example 48MiB (default: MAX_MEDIA_BYTES)",
    )
    parser.add_argument(
        "--max-duration",
        type=_parse_duration,
        metavar="DURATION",
        help="maximum duration, for example 600, 10m or 1h (default: MAX_MEDIA_DURATION_SECONDS)",
    )
    parser.add_argument(
        "--metadata-timeout",
        type=_positive_int,
        metavar="SECONDS",
        help="yt-dlp metadata timeout (default: EXTRACTOR_METADATA_TIMEOUT_SECONDS)",
    )
    parser.add_argument(
        "--download-timeout",
        type=_positive_int,
        metavar="SECONDS",
        help="yt-dlp download timeout (default: EXTRACTOR_DOWNLOAD_TIMEOUT_SECONDS)",
    )
    parser.add_argument(
        "--ffmpeg-timeout",
        type=_positive_int,
        metavar="SECONDS",
        help="FFmpeg processing timeout (default: FFMPEG_TIMEOUT_SECONDS)",
    )
    parser.add_argument("--verbose", action="store_true", help="show tracebacks on errors")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="workbench.engine_cli",
        description=(
            "Inspect and download public social videos through the same engine used by the "
            "worker, without Telegram, PostgreSQL or Redis."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")

    inspect_parser = subparsers.add_parser(
        "inspect",
        aliases=["i"],
        help="show metadata, formats and the selected format",
    )
    inspect_parser.add_argument("url", help="public TikTok, Instagram, YouTube or Facebook link")
    _add_engine_arguments(inspect_parser)

    download_parser = subparsers.add_parser(
        "download",
        aliases=["d"],
        help="inspect, download, verify and prepare an MP4",
    )
    download_parser.add_argument("url", help="public TikTok, Instagram, YouTube or Facebook link")
    download_parser.add_argument(
        "--output",
        metavar="PATH",
        help="output file path (default: workbench/downloads/<platform>-<id>-<time>.mp4)",
    )
    download_parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite the output file if it already exists",
    )
    _add_engine_arguments(download_parser)

    interactive_parser = subparsers.add_parser(
        "interactive",
        aliases=["shell", "menu"],
        help="start the interactive menu (default when no command is given)",
    )
    _add_engine_arguments(interactive_parser)

    return parser


async def _run(args: argparse.Namespace, options: EngineOptions) -> int:
    workbench = EngineWorkbench(options, verbose=args.verbose)
    command = args.command or "interactive"
    if command in {"interactive", "shell", "menu"}:
        return await _interactive(workbench, options)

    try:
        inspection = await workbench.inspect(args.url)
    except AppError as exc:
        _print_app_error(exc, verbose=args.verbose)
        return 1
    except Exception as exc:
        _print_unexpected_error(exc, verbose=args.verbose)
        return 1

    _print_inspection(inspection, options)
    if command in {"inspect", "i"}:
        return 0

    try:
        output = Path(args.output) if args.output else None
        await workbench.download(inspection, output=output, force=args.force)
    except AppError as exc:
        _print_app_error(exc, verbose=args.verbose)
        return 1
    except Exception as exc:
        _print_unexpected_error(exc, verbose=args.verbose)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    settings = get_settings()
    options = _build_options(args, settings)
    try:
        return asyncio.run(_run(args, options))
    except KeyboardInterrupt:
        print("\nCancelled.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
