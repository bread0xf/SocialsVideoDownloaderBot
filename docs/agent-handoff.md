# Temporary Agent Handoff

> Snapshot date: 2026-11-06. This is a temporary working handoff for the next implementation agent. Delete or replace it when Phase 2 starts. The durable status table remains `docs/implementation-status.md`.

## Read first

1. `AGENTS.md`
2. `backend_specs/` — authoritative implementation baseline; it wins over `docs/`
3. `backend_specs/docs/09-open-decisions.md` — do not invent values marked OPEN/PROPOSED/VERIFY
4. `docs/implementation-status.md` — completed vs partial requirements
5. This handoff

## Current state

Phase 0 and the Phase 1 free-tier vertical slice are implemented. The bot can accept a supported public video URL, create an idempotent download job, reserve quota, publish through the transactional outbox, process with the yt-dlp adapter, prepare media with FFmpeg/FFprobe, deliver via a Telegram abstraction, commit/release quota, and use an expiring media cache.

The Phase 0/1 implementation is committed in `1e92011`. The working tree currently holds documentation/decision updates only. Do not commit unless the user explicitly asks.

### Implemented and covered

- Config/logging, FastAPI health routes, ARQ worker, Docker Compose, Alembic wiring.
- Initial schema and seed data: free/premium plans and TikTok/Instagram/YouTube/Facebook registry rows.
- Strict URL normalization for the four MVP platforms, including canonicalization and tracking-query stripping.
- SSRF-oriented ingestion checks: scheme/host/port/credential validation, IP/localhost blocking, DNS global-address guard.
- Telegram user upsert.
- Entitlement resolution with active/cancelled subscriptions through `paid_through`, free fallback, plan/config resolution caps.
- Download submission with idempotency key, active-job limit, media key, quota reservation, and outbox event.
- Quota reserve/commit/release under a per-user PostgreSQL advisory lock, with append-only ledger entries.
- Outbox dispatch to ARQ with retry/attempt tracking.
- yt-dlp subprocess adapter with argv arrays, isolated environment, timeouts, process-group kill, output caps, and safe failure classification.
- Format selection with plan-height ceiling, H.264/AAC preference, combined vs separate streams, and size checks.
- FFprobe validation, FFmpeg remux/transcode to MP4, cache lookup/upsert, atomic cache-file storage.
- Worker success/failure/retry paths, cache-first flow with entitlement recheck, stale-job reconciliation, cache cleanup.
- Telegram `/start`, `/help`, `/status`, URL intake, and queued response.
- `/api/v1/platforms` endpoint.

### Partial or still unverified

- yt-dlp adapter: no tests against real extractors or redirect chains.
- FFmpeg/FFprobe: no real media-fixture integration test; worker tests mock probing.
- Telegram delivery: exercised with fakes, not the live Bot API.
- Cache expiry/size-eviction and stale-job reconciliation: implemented but no dedicated tests.
- Bot command/URL handlers: no handler-level tests.
- Extractor redirect/SSRF validation: ingestion DNS guard exists; redirect validation at download/extraction time is still pending.
- Production operational checks are not complete.

## Quality gate status

Last run on 2026-11-06:

```bash
uv run ruff check .                 # passed
uv run ruff format --check .        # passed
uv run mypy backend apps            # passed, 49 files
uv run pytest -q                    # passed, 89 tests
```

Test split: 77 unit tests, 12 integration tests.

Integration tests need PostgreSQL. They use `TEST_DATABASE_URL` when set, otherwise create a temporary `svdb_test_<hex>` database on the server in `DATABASE_URL` and drop it afterwards. If PostgreSQL is unavailable the integration fixture skips.

Local schema was applied with `uv run alembic upgrade head`.

## Important commands

```bash
# Dependencies and local services
uv sync --all-groups
docker compose up -d postgres redis
uv run alembic upgrade head

# Processes
uv run svdb-api
uv run svdb-bot
uv run svdb-worker

# Gates
uv run ruff check .
uv run ruff format --check .
uv run mypy backend apps
uv run pytest -q
```

## Key code map

| Area | Files |
|---|---|
| Bot entry and commands | `apps/bot/main.py` |
| Settings | `backend/core/config.py`, `.env.example` |
| Error codes | `backend/core/errors.py` |
| Lagos quota period helpers | `backend/core/quota.py` |
| ORM models | `backend/database/models.py` |
| Initial migration and seeds | `migrations/versions/71cd52ac280f_initial_schema.py` |
| URL validation/normalization/DNS guard | `backend/platforms/urls.py` |
| Platform status registry | `backend/platforms/registry.py` |
| yt-dlp adapter | `backend/platforms/adapters/ytdlp.py` |
| Entitlements | `backend/entitlements/service.py` |
| Quota reservation/ledger | `backend/usage/service.py` |
| Download submission | `backend/downloads/service.py` |
| Job state machine | `backend/downloads/state.py` |
| Transactional outbox | `backend/downloads/outbox.py` |
| Format selection | `backend/media/selection.py` |
| FFprobe/FFmpeg | `backend/media/ffprobe.py`, `backend/media/processing.py` |
| Cache metadata/files | `backend/media/cache.py`, `backend/storage/cache.py` |
| Telegram delivery | `backend/delivery/telegram.py` |
| Worker tasks | `backend/workers/tasks.py`, `backend/workers/settings.py` |
| Platform API | `backend/api/routes/platforms.py` |
| Unit tests | `tests/unit/` |
| Integration tests | `tests/integration/` |

## Non-obvious implementation notes

- `premium_daily_limit` defaults to `20` (owner-approved OD-02, 2026-11-06). The premium plan row remains nullable and falls back to this configuration value.
- Media cache keys include platform, source ID, entitlement output profile, and `processing_version`. Changing entitlement or processing version naturally avoids stale reuse.
- Worker cache hits still resolve the current entitlement first; the cache-hit integration test proves an expired Premium subscription falls back to the free profile.
- Quota counts `reserved` and `committed` reservations for the current Lagos day; `released` reservations do not count. Only successful delivery commits usage.
- Terminal worker failure releases the reservation and never writes a commit ledger entry. Retryable failure requeues without releasing.
- The outbox uses event IDs as ARQ job IDs to avoid duplicate enqueue attempts.
- Telegram PTB v22 exposes `InputFile`; `FSInputFile` is not available from `telegram` in this version.
- `WorkerSettings.on_startup`/`on_shutdown` use a typed cast because of arq's `StartupShutdown` protocol typing.
- Async code must not call blocking `pathlib` operations directly; Ruff `ASYNC240` is enabled. Use `asyncio.to_thread` for file I/O when needed.
- The initial migration was generated and formatted with Ruff. Prefer Alembic autogenerate for future schema changes; do not rely on `Base.metadata.create_all` outside tests.
- Do not log bot tokens, payment secrets, authorization headers, cookies, full sensitive URLs, or raw payment payloads.

## Recommended next work

1. Extraction engine: split metadata and download timeouts, add real extractor redirect/SSRF validation, and add yt-dlp fixture tests.
2. Enforce tier-specific size and duration limits (free 48 MiB / 600 s vs. Premium 1.9 GB / 1800 s) in the worker.
3. Add real media fixture tests for the FFmpeg + FFprobe path.
4. Add Telegram delivery error-mapping tests and a live/manual Bot API smoke test procedure.
5. Add cache expiry/size-eviction and stale-job reconciliation integration tests.
6. Add handler tests for `/start`, `/help`, `/status`, duplicate Telegram updates, and URL intake.
7. Improve `/health/ready` coverage with live PostgreSQL/Redis checks.
8. Re-run all quality gates and update `docs/implementation-status.md`.

## Decision status (updated 2026-11-06)

Resolved by the owner:

- OD-01 Premium price: 150 Telegram Stars per 30-day subscription.
- OD-02 Premium allowance: 20 included downloads per `Africa/Lagos` day; `premium_daily_limit` now defaults to 20.
- OD-03 delivery direction: bot-managed chat/sponsor ads; one ad grants one extra download. No official Telegram rewarded-ad API exists; mechanism must be server-verified.
- OD-07 verified: 50 MB cloud Bot API upload; 2000 MB with a local Bot API server (`--local`). Local server recommended for Premium 4K.
- OD-06 approved: free 48 MiB / 10 min / 1 job; Premium 1.9 GB / 30 min / 2 jobs; worker concurrency 2; metadata 60 s, download 900 s, FFmpeg 600 s, job 1800 s, max age 7200 s; cache 50 GiB.
- OD-08 approved: free users only, one sponsor placement per successful download sent after delivery; no PII or preference tracking; moderation deferred.

Still open:

- OD-03 exact ad mechanism (single-use token vs. third-party postback).
- OD-04 reward credit expiry (proposed: end of the Lagos quota day earned).
- OD-05 daily reward cap (proposed: 10/user/day).
- OD-08 content moderation, campaign billing and targeting.

Use configuration or clearly named development defaults only where necessary, and record the temporary choice. See `backend_specs/docs/09-open-decisions.md` for the full record.

## Safety and scope reminders

- MVP platforms only: TikTok, Instagram, YouTube, Facebook.
- Public content only. Never request passwords, cookies, browser profiles, session tokens, or private-account credentials.
- No DRM, paywall, private-content, or access-control bypass.
- No arbitrary direct-file URL downloader.
- No playlists, channels, live streams, batch jobs, or non-Telegram delivery in MVP.
- PostgreSQL is authoritative; Redis/ARQ are not ledgers.
- Keep the modular monolith; do not split services without an approved architecture decision.
