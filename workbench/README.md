# Engine Workbench

A small developer CLI for exercising the download/extraction engine without Telegram,
PostgreSQL, Redis, quotas or billing. It uses the same URL validation, yt-dlp adapter,
format selection, FFmpeg/FFprobe processing and size/duration checks as the worker.

## Requirements

- `uv sync --all-groups`
- `yt-dlp`, FFmpeg and FFprobe available (the project virtualenv and container have them)
- Deno for YouTube JavaScript challenges, as required by `yt-dlp-ejs`
- Network access to the supported platforms

## Usage

Interactive menu (default):

```bash
uv run python -m workbench.engine_cli
```

Inspect only:

```bash
uv run python -m workbench.engine_cli inspect 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'
```

Download and prepare a verified MP4:

```bash
uv run python -m workbench.engine_cli download 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'
```

Choose an output file:

```bash
uv run python -m workbench.engine_cli download 'URL' --output ./my-video.mp4 --force
```

Override the default limits:

```bash
uv run python -m workbench.engine_cli inspect 'URL' --max-height 720 --max-bytes 96MiB
uv run python -m workbench.engine_cli download 'URL' --max-duration 15m
```

Accepted size units: `B`, `KiB`, `MiB`, `GiB` (also `KB`, `MB`, `GB`). Accepted duration
units: plain seconds, `s`, `m`, `h`.

## Output

Files are written to `workbench/downloads/` by default. That directory is git-ignored.
Temporary workspaces are created and deleted under the same directory for each download.

## What it does not do

- No Telegram delivery.
- No database, job records, outbox, Redis/ARQ, quota reservation or entitlements.
- No media cache reuse, cleanup policy, retries or stale-job reconciliation.
- No Premium/payment/reward behavior. Limits are whatever you pass on the command line
  or the configured workbench defaults.

Default limits come from `.env`/environment through `backend.core.config.Settings`
(`FREE_MAX_RESOLUTION_P`, `MAX_MEDIA_BYTES`, `MAX_MEDIA_DURATION_SECONDS`, extractor
timeouts and `FFMPEG_TIMEOUT_SECONDS`).
