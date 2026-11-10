# Implementation Status

> **Authority:** `backend_specs/` is the approved implementation baseline and wins any conflict with this file. This document is the only tracker for what is actually implemented. Do not mark an item complete without code and test references.
>
> **Last reviewed:** 2026-11-09.

## Current state

The free-tier pipeline and the standalone v0 bot are implemented. Extraction has been live-verified for public YouTube, TikTok, Instagram and Facebook videos. The system is **not production-ready**: billing, rewarded ads and sponsors do not exist; Telegram delivery has only been exercised with fakes; controlled egress and tier-specific size/duration enforcement are incomplete.

A Railway development environment (API + bot + worker + managed Postgres/Redis) is planned; its status is recorded under [Deployed environments](#deployed-environments).

## Requirement status

| Capability | Status | Code | Tests | Notes |
|---|---|---|---|---|
| Repository reconnaissance | Implemented | `README.md`, `backend_specs/` | — | Conflicts reconciled: Lagos quota, 480p free ceiling, 24h retention |
| Configuration, logging, runtime skeleton | Implemented | `backend/core/config.py`, `backend/core/logging.py` | `tests/unit/test_config.py`, `tests/unit/test_logging.py` | Fail-fast production token check; locked defaults |
| Compose topology and health endpoints | Implemented | `compose.yaml`, `Dockerfile`, `backend/api/` | `tests/unit/test_health.py` | `/health/live` tested; `/health/ready` needs live Postgres/Redis |
| Alembic schema and seed data | Implemented | `alembic.ini`, `migrations/` | Integration fixtures use current metadata | Free/Premium plans and four platform-registry rows seeded |
| Main bot `/start`, `/help`, `/status`, URL intake | Partial | `apps/bot/main.py` | — | Handlers implemented; no handler-level tests |
| v0 standalone bot | Implemented (development only) | `apps/bot_v0/`, `backend/downloads/engine.py` | `tests/unit/test_bot_v0_*.py`, `test_inprocess_engine.py` | Single process, in-memory quota, no Postgres/Redis/worker; not a production ledger |
| URL validation and platform registry | Implemented | `backend/platforms/urls.py`, `backend/platforms/registry.py` | `tests/unit/test_urls.py`, `test_registry.py` | Canonicalization, port/credential/IP/localhost blocking, DNS global-address guard |
| Persistent download jobs | Implemented | `backend/database/models.py`, `backend/downloads/service.py` | `tests/integration/test_download_submission.py` | Idempotent submission, active-job limit, outbox event |
| Atomic quota reservation | Implemented | `backend/usage/service.py` | `tests/integration/test_usage_quota.py` | Per-user advisory lock; reserve/commit/release; append-only ledger |
| Transactional outbox and ARQ dispatch | Implemented | `backend/downloads/outbox.py`, `backend/workers/tasks.py` | `tests/integration/test_outbox_dispatch.py` | Each event published once; failed enqueue remains retryable |
| yt-dlp adapter | Implemented | `backend/platforms/adapters/ytdlp.py` | `tests/unit/test_ytdlp_adapter.py`, `tests/integration/test_live_extraction.py` | Split metadata/download timeouts, isolated subprocess env, platform error mapping, DRM/availability checks, final-URL validation |
| Automatic format selection | Implemented | `backend/media/selection.py` | `tests/unit/test_format_selection.py` | Plan ceiling, H.264/AAC preference, combined/separate streams, size estimates, portrait quality, silent video, DRM exclusion |
| FFmpeg/FFprobe validation and preparation | Implemented | `backend/media/ffprobe.py`, `backend/media/processing.py` | `tests/integration/test_media_processing.py`, worker tests | Orientation-aware downscale; remux when already compliant, otherwise transcode |
| Telegram media delivery | Implemented | `backend/delivery/telegram.py`, `backend/delivery/presentation.py`, `backend/workers/tasks.py` | `tests/integration/test_worker_outcomes.py`, `tests/unit/test_telegram_delivery.py`, `tests/unit/test_presentation.py` | Live delivery confirmed 2026-11-10 after fixing `InputFile(str(path))`, which uploaded the path text instead of the video bytes. Captions carry title, uploader and quality; filenames use platform-source ID |
| Usage commit/release | Implemented | `backend/usage/service.py`, `backend/workers/tasks.py` | `tests/integration/test_worker_outcomes.py` | Terminal failure releases quota and writes no commit entry |
| Premium entitlement recheck on cache hit | Implemented | `backend/entitlements/service.py`, `backend/workers/tasks.py` | `tests/integration/test_worker_outcomes.py` | Expired subscription falls back to Free before cache lookup |
| 24-hour cache cleanup | Partial | `backend/workers/tasks.py`, `backend/storage/cache.py` | — | Expiry and size eviction implemented; dedicated tests pending |
| Recovery and idempotency | Partial | `backend/workers/tasks.py`, `backend/downloads/state.py` | `test_worker_outcomes.py`, `test_outbox_dispatch.py` | Retry/terminal failure and outbox retry covered; stale-job reconciliation tests pending |
| SSRF and redirect validation | Partial | `backend/platforms/urls.py`, `backend/platforms/adapters/ytdlp.py` | `tests/unit/test_urls.py` | Ingestion DNS guard wired into bot and worker; final extracted URL allowlisted; controlled egress/DNS-rebinding enforcement pending |
| Operational limits | Partial | `backend/core/config.py` | `tests/unit/test_config.py` | Approved global defaults applied; tier-specific size/duration enforcement pending |
| Sponsor placements | Not started | — | — | Policy approved: Free users only, one placement after successful delivery |
| Premium payment integration | Not started | — | — | 150 Stars / 30 days and 20/day approved 2026-11-06; no billing module |
| Rewarded ads | Not started | — | — | Bot-managed chat ads; 1 credit per verified event. Daily cap and expiry open |
| Sponsor system and Mini App | Deferred | — | — | Later phase |

## Verification log

| Date | Gate | Result |
|---|---|---|
| 2026-11-06 | Phase 0 skeleton | 9 passed |
| 2026-11-06 | Phase 1 free-tier slice | 89 passed |
| 2026-11-06 | Extraction hardening | 142 passed, 5 skipped; live extraction passed for all four platforms |
| 2026-11-09 | v0 bot | 168 passed, 17 skipped (Postgres unavailable locally); profile setup applied to the live bot |
| 2026-11-09 | Docs consolidation and Railway readiness | Ruff and format passed; mypy passed (59 files); 183 passed, 5 skipped (live extraction gated); Docker image built successfully |
| 2026-11-10 | Telegram upload fix | Ruff and format passed; mypy passed (59 files); 184 passed, 5 skipped; fake Bot API probe confirmed the uploaded video bytes are byte-identical to the source file |
| 2026-11-10 | Delivery metadata polish | Ruff and format passed; mypy passed (60 files); 192 passed, 5 skipped; migration adds `media_cache.title`/`uploader` and was applied to a fresh database |

Integration tests require PostgreSQL. Set `TEST_DATABASE_URL` to an isolated database, or let the suite create a temporary database on the server in `DATABASE_URL`. When PostgreSQL is unavailable those tests skip rather than fail.

### Live extraction

| Platform | Metadata | Download and prepare | Notes |
|---|---|---|---|
| YouTube | Pass | Pass | Requires `yt-dlp-ejs` and Deno 2.3+ |
| TikTok | Pass | Pass | Portrait 540p downscaled to the 480p ceiling |
| Instagram | Pass | Pass | Silent reel path exercised |
| Facebook | Pass | Pass | Some older sample URLs hit yt-dlp extractor limits |

Live tests are gated by `SVDB_LIVE_EXTRACTION=1`; see `tests/integration/test_live_extraction.py`.

## Deployed environments

| Environment | Status | Notes |
|---|---|---|
| Local Docker Compose | Implemented | Postgres, Redis, API, bot and worker; worker mounts the media volume |
| Railway development | API and worker live; bot pending token | API healthy at `https://socialsvideodownloaderbot-production.up.railway.app`; migrations applied; worker cron dispatching the outbox with no schema errors. Bot awaits `TELEGRAM_BOT_TOKEN`. Runbook in `docs/operations/railway-dev-environment.md` |
| Production | Not deployed | Hosting decision D-12 remains open; see `docs/project/unresolved-decisions.md` |

## Known gaps and next work

1. Enforce tier-specific size, duration and concurrency limits.
2. Add automated live Telegram delivery tests and map Bot API errors.
3. Add cache-eviction and stale-job reconciliation tests.
4. Add handler tests for `apps/bot` `/start`, `/help`, `/status` and URL intake.
5. Add controlled egress or network policy for full DNS-rebinding protection.
6. Implement billing, rewarded ads and sponsor placements according to `backend_specs/docs/05`.
7. Resolve the reward daily cap and credit expiry (D-05, D-06).
8. Fix role-specific production configuration validation before any production deployment: today `APP_ENV=production` requires a Telegram token for every process, including the API.

## Decisions

Approved product and operational values live in `backend_specs/docs/09-open-decisions.md` and `docs/project/unresolved-decisions.md`. Stale text in `backend_specs/docs/02-database-specification.md` and `backend_specs/KICKOFF_PROMPT.md` about Premium pricing is superseded by `docs/09`; do not edit frozen specifications without owner approval as an erratum.
