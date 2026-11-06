# 07 — Operations and Deployment

## 1. Runtime processes

- `bot`: Telegram polling/webhook adapter (select deployment mode explicitly; polling is simplest for local MVP).
- `api`: FastAPI health and later callback/Mini App endpoints.
- `worker`: ARQ extraction/processing/delivery tasks.
- `scheduler`: cleanup, reconciliation and subscription expiry tasks.

One image/codebase may run with different commands per service.

## 2. Infrastructure

Docker Compose services:
- PostgreSQL with persistent volume and health check.
- Redis with health check and persistence policy appropriate to queue role.
- Bot.
- API.
- Worker.
- Scheduler (can initially be a single coordinated process).

Use service health dependencies, restart policies, non-root worker where practical, resource limits and explicit network boundaries. Do not expose PostgreSQL/Redis publicly in production.

## 3. Configuration

Use Pydantic Settings. `.env.example` must document every required setting without real values.

Expected configuration groups:
- application environment/log level;
- Telegram bot token and polling/webhook mode;
- PostgreSQL DSN;
- Redis DSN;
- storage root and cache quota;
- `QUOTA_TIMEZONE= Africa/Lagos`;
- free allowance and quality ceilings;
- Premium allowance/price (unset until approved);
- extractor/FFmpeg timeouts and resource limits;
- queue concurrency/retries;
- Telegram upload cap (verified deployment value);
- callback secrets/provider configuration (disabled until selected).

Fail fast on missing required production settings. Never silently substitute fake production credentials.

## 4. Dependencies

Python:
- `python-telegram-bot`
- `fastapi`
- `uvicorn`
- `yt-dlp`
- `yt-dlp-ejs` (JavaScript challenge solver scripts required by the YouTube extractor)
- `SQLAlchemy`
- `asyncpg`
- `alembic`
- `redis`
- `arq`
- `pydantic`
- `pydantic-settings`
- `httpx` where directly used
- `structlog` recommended for structured logging

External:
- FFmpeg + FFprobe
- PostgreSQL
- Redis
- Docker Engine + Docker Compose
- Deno 2.3+ (required for yt-dlp EJS challenge solving on YouTube; re-verify current yt-dlp requirements at deployment time).

Development:
- `pytest`, `pytest-asyncio`, `pytest-cov`, `ruff`
- `mypy` recommended
- `respx` for HTTPX mocking
- `testcontainers` for integration tests
- `uv` for environment and dependency management

Pin compatible versions during implementation and commit lockfile. Do not blindly copy old pins.

## 5. Observability

Structured logs include request/job ID, platform, stage, duration, error category and worker identifier. Use a protected internal user reference, not raw Telegram IDs in broad logs. Never log bot tokens, cookies, raw provider secrets or full query-bearing URLs.

Metrics:
- requested/completed/failed downloads;
- success rate by platform;
- extraction/processing/delivery latency;
- Telegram delivery failures;
- queue depth/wait time;
- worker concurrency;
- output sizes/cache hit rate/storage usage;
- quota and reward usage;
- payment/subscription lifecycle events.

## 6. Recovery and maintenance

- Bounded retries with exponential backoff and jitter.
- Graceful worker shutdown.
- Stale job/lease recovery.
- Outbox retry and monitoring.
- Cache expiry and orphan-file cleanup.
- PostgreSQL backups and restore drills.
- Disk/queue backlog alerts.
- Dependency update and platform compatibility verification routine.

## 7. Launch checklist

- Verify Telegram Bot API upload limits and deployment method.
- Verify current yt-dlp extractor requirements and supported content.
- Configure resource ceilings and storage quota.
- Configure production secrets outside git.
- Verify DB backup/restore.
- Test worker restart and stale-job recovery.
- Confirm all unresolved monetization decisions before enabling those features.
