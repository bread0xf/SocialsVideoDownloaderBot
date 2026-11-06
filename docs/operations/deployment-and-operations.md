# Deployment and Operations

**Deployment direction:** Docker Compose for development and initial production deployment. Validate resource requirements and hosting constraints before launch.

## Services

Suggested Compose services:
- `bot`
- `api`
- `worker`
- `scheduler`
- `outbox-publisher` (may be combined with scheduler initially)
- `postgres`
- `redis`

Use one application image with different commands/entrypoints where practical.

## Extraction runtime

The application image must include:
- `yt-dlp` and `yt-dlp-ejs` (Python dependencies).
- A supported JavaScript runtime: Deno 2.3+ is installed in the image and is required for YouTube JS challenge solving.
- FFmpeg and FFprobe.

Keep yt-dlp current; extractor changes and temporary platform blocks are expected. Live smoke tests are available in `tests/integration/test_live_extraction.py` and are gated by `SVDB_LIVE_EXTRACTION=1`.

## Environment configuration

Document and validate variables such as:
- `APP_ENV`
- `LOG_LEVEL`
- `DATABASE_URL`
- `REDIS_URL`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_WEBHOOK_SECRET` (if webhook mode)
- `PUBLIC_API_BASE_URL`
- `MEDIA_CACHE_DIR`
- `MEDIA_CACHE_MAX_BYTES`
- `MEDIA_RETENTION_HOURS`
- `JOB_TIMEOUT_SECONDS`
- `EXTRACTOR_METADATA_TIMEOUT_SECONDS`
- `EXTRACTOR_DOWNLOAD_TIMEOUT_SECONDS`
- `FFMPEG_TIMEOUT_SECONDS`
- `MAX_MEDIA_BYTES`
- `MAX_MEDIA_DURATION_SECONDS`
- `TELEGRAM_UPLOAD_MAX_BYTES`
- `WORKER_CONCURRENCY`
- `FREE_DAILY_LIMIT`
- `FREE_MAX_RESOLUTION_P`
- `PREMIUM_MAX_RESOLUTION_P`
- `PREMIUM_DAILY_LIMIT`
- Billing/reward provider secrets when those integrations are approved.

Do not commit real values. Keep `.env.example` placeholders nonfunctional.

## Telegram delivery constraints

**VERIFY before launch:** Current Telegram Bot API upload limits, method-specific constraints, file size behavior, local Bot API server implications, and any hosting/bandwidth costs. Do not hard-code assumed limits into architecture. Enforce configured maximums and return a clear message when a file cannot be delivered.

## Storage

- Use a dedicated volume for cache and temporary workspaces.
- Enforce cache byte limit and TTL.
- Keep temporary and durable cache directories separate.
- Monitor disk usage and alert before exhaustion.
- Back up PostgreSQL; cache media need not be backed up unless product requirements change.
- Encrypt backups and restrict access.

## Reliability

- Configure restart policies and health checks.
- Use graceful shutdown and stop claiming new jobs during termination.
- Persist job state before queue publication.
- Reconcile stale jobs and unpublished outbox events.
- Configure bounded retries and dead-letter/failed-job handling.
- Test restore from database backup.

## Observability

Metrics:
- Queue depth and oldest queued job age.
- Worker utilization and job duration.
- Per-platform success/failure.
- Telegram delivery outcome.
- PostgreSQL connection/transaction health.
- Redis health.
- Cache size/hit rate/evictions.
- Disk, memory and CPU.
- Payment and reward callback verification failures.

Logs must be structured and redact secrets and sensitive URL parameters.

## Release checklist

- [ ] Product decisions in `unresolved-decisions.md` resolved.
- [ ] Platform/legal/policy review completed.
- [ ] Telegram delivery constraints verified.
- [ ] Secrets configured outside repository.
- [ ] Database migrations reviewed and tested.
- [ ] Backup/restore tested.
- [ ] SSRF and worker isolation tests pass.
- [ ] Rate limits and resource limits configured.
- [ ] Monitoring and alerting configured.
- [ ] Incident and token-rotation procedures documented.
- [ ] Terms, privacy notice and support/takedown contact published.
