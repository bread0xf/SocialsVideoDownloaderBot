# Deployment and Operations

**Status:** Local Docker Compose is implemented. A hosted development environment runs on Railway (see `railway-dev-environment.md`). Production hosting is not chosen; D-12 remains open.

## Processes

One image runs three application processes:

| Process | Command | Responsibility |
|---|---|---|
| API | `svdb-api` | FastAPI health/readiness and `GET /api/v1/platforms` |
| Bot | `svdb-bot` | Telegram long polling, URL intake, job submission, status |
| Worker | `svdb-worker` | ARQ job processing plus cron: outbox dispatch, cache cleanup, stale-job reconciliation |

There is no separate scheduler or outbox-publisher process. Compose also runs PostgreSQL and Redis; only the worker mounts the media volume.

The standalone `svdb-bot-v0` is a development/demo process with in-memory quota. Do not deploy it as a production service.

## Extraction runtime

The image includes:

- `yt-dlp` and `yt-dlp-ejs` as Python dependencies.
- Deno 2.3+ for YouTube JavaScript challenge solving.
- FFmpeg and FFprobe.

Keep yt-dlp current and expect extractor breakage. Live smoke tests are gated by `SVDB_LIVE_EXTRACTION=1` in `tests/integration/test_live_extraction.py`.

## Environment configuration

Core variables (see `.env.example` for the full list):

- `APP_ENV`, `LOG_LEVEL`, `LOG_JSON`
- `DATABASE_URL`, `REDIS_URL`
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_POLLING`
- `PORT` (API; default 8000)
- `MEDIA_ROOT`, `MEDIA_CACHE_MAX_BYTES`, `MEDIA_RETENTION_HOURS`
- `MAX_MEDIA_BYTES`, `MAX_MEDIA_DURATION_SECONDS`, `TELEGRAM_UPLOAD_MAX_BYTES`
- `EXTRACTOR_METADATA_TIMEOUT_SECONDS`, `EXTRACTOR_DOWNLOAD_TIMEOUT_SECONDS`, `FFMPEG_TIMEOUT_SECONDS`
- `JOB_TIMEOUT_SECONDS`, `JOB_MAX_AGE_SECONDS`, `WORKER_CONCURRENCY`
- `FREE_DAILY_LIMIT`, `FREE_MAX_RESOLUTION_P`, `PREMIUM_DAILY_LIMIT`, `PREMIUM_MAX_RESOLUTION_P`

`DATABASE_URL` accepts `postgres://`, `postgresql://` or `postgresql+asyncpg://`; it is normalized to the asyncpg driver at settings load.

Do not commit real values. Keep `.env.example` placeholders nonfunctional.

## Telegram delivery constraints

The cloud Bot API upload cap is 50 MB and the application enforces a 48 MiB effective maximum, so Free deliveries fit and oversized media fails with a clear error instead of splitting. Premium 4K delivery requires a local Bot API server (`--local`, up to 2000 MB) and cannot be validated on the cloud API. Confirm current Telegram limits before launch; do not hard-code assumptions.

## Health and readiness

- `GET /health/live` — process liveness; no dependency checks.
- `GET /health/ready` — checks PostgreSQL and Redis; returns 503 when a dependency is unavailable.

Use `/health/live` for container orchestration liveness. Alert on `/health/ready` failures separately.

## Migrations

- Apply with `alembic upgrade head`.
- In Compose, run it once before starting services.
- On Railway, run it as the API service's pre-deploy command (or as a one-off step); never enable it on bot and worker at the same time.
- Migrations are forward-only. Back up PostgreSQL before applying on a shared environment.

## Storage

- `MEDIA_ROOT` holds `workspaces/<job_uuid>` and `cache/<media_key>.mp4`.
- Workspaces are temporary and removed after processing.
- Cache is bounded by `MEDIA_CACHE_MAX_BYTES` and the locked 24-hour retention.
- Size the volume above the cache cap so cleanup runs before the disk fills.
- Cache media need not be backed up; PostgreSQL must be.

## Observability

Structured logs already emit lifecycle events: `download_started`, `download_retry_scheduled`, `download_failed`, `outbox_dispatched`, `cache_cleanup_completed`, `stale_jobs_reconciled`. Download completion events include `elapsed_ms` so engine and delivery duration can be measured from logs without URLs or media content.

Recommended production metrics (not yet implemented): queue depth and oldest job age, worker utilization and job duration, per-platform success/failure, Telegram delivery outcome, PostgreSQL/Redis health, cache hit rate and evictions, disk/memory/CPU. Logs must redact tokens, authorization headers and sensitive URL parameters.

## Release checklist

- [ ] Product decisions in `docs/project/unresolved-decisions.md` resolved.
- [ ] Platform/legal/policy review completed.
- [ ] Telegram delivery constraints verified.
- [ ] Secrets configured outside the repository.
- [ ] Migrations reviewed and tested; backup taken.
- [ ] Backup/restore tested.
- [ ] SSRF, export isolation and controlled-egress checks pass.
- [ ] Rate and resource limits configured.
- [ ] Monitoring and alerting configured.
- [ ] Incident and token-rotation procedures documented.
- [ ] Terms, privacy notice and support/takedown contact published.
