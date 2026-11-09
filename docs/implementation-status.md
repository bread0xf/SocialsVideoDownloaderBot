# Implementation Status

> Updated as implementation proceeds. Do not mark an item complete without pointing to code and tests.

| Requirement | Status | Code reference | Test reference | Notes |
|---|---|---|---|---|
| Repository reconnaissance | Complete | `README.md`, `backend_specs/` | — | Conflicts reconciled: Lagos quota, 480p free, 24h retention |
| Runtime/config/logging skeleton | Complete | `backend/core/config.py`, `backend/core/logging.py`, `pyproject.toml` | `tests/unit/test_config.py` | Fail-fast production token check; locked defaults |
| Docker Compose + health checks | Complete | `compose.yaml`, `Dockerfile`, `backend/api/app.py`, `backend/api/routes/health.py` | `tests/unit/test_health.py` | `/health/live` tested; `/health/ready` needs live DB/Redis |
| Alembic schema | Complete | `alembic.ini`, `migrations/env.py`, `migrations/versions/71cd52ac280f_initial_schema.py` | Integration fixtures create the current metadata | Initial schema plus seeded free/premium plans and MVP platform registry |
| Telegram `/start`, `/help`, `/status` | Partial | `apps/bot/main.py` | — | Handlers implemented; handler tests still pending |
| v0 standalone bot | Complete (development) | `apps/bot_v0/`, `backend/downloads/engine.py` | `tests/unit/test_bot_v0_handlers.py`, `test_bot_v0_state.py`, `test_bot_v0_messages.py`, `test_bot_v0_setup.py`, `test_inprocess_engine.py` | Single process, no PostgreSQL/Redis/worker; in-memory quota; free limits only; branded profile via `svdb-bot-v0-setup`; HTML cards, inline buttons and stage progress; not a production ledger |
| URL validation/platform registry | Complete | `backend/platforms/urls.py`, `backend/platforms/registry.py` | `tests/unit/test_urls.py`, `tests/unit/test_registry.py` | Canonicalization, port/credential/IP/localhost blocking, DNS-global-address guard |
| Persistent download jobs | Complete | `backend/database/models.py`, `backend/downloads/service.py` | `tests/integration/test_download_submission.py` | Idempotent submission, active-job limit, outbox event |
| Atomic quota reservation | Complete | `backend/usage/service.py` | `tests/integration/test_usage_quota.py` | Advisory lock, reserve/commit/release, append-only ledger entries |
| Transactional outbox + ARQ | Complete | `backend/downloads/outbox.py`, `backend/workers/tasks.py` | `tests/integration/test_outbox_dispatch.py` | Publishes each event once; failed enqueue remains retryable |
| yt-dlp adapter | Complete | `backend/platforms/adapters/ytdlp.py` | `tests/unit/test_ytdlp_adapter.py`, `tests/integration/test_live_extraction.py` | Split metadata/download timeouts, EJS solver dependency, platform error mapping, DRM/availability checks, final-URL validation; live smoke passed for all four platforms 2026-11-06 |
| Automatic format selection | Complete | `backend/media/selection.py` | `tests/unit/test_format_selection.py` | Plan ceiling, H.264/AAC preference, combined/separate streams, bitrate size estimates, portrait quality height, downscale fallback, silent video, DRM exclusion |
| FFmpeg/FFprobe validation | Complete | `backend/media/ffprobe.py`, `backend/media/processing.py` | `tests/integration/test_media_processing.py`, `tests/integration/test_live_extraction.py`, worker tests | Orientation-aware downscale; synthetic landscape/portrait and live media preparation passed 2026-11-06 |
| Telegram media delivery | Partial | `backend/delivery/telegram.py`, `backend/workers/tasks.py` | `tests/integration/test_worker_outcomes.py` | Delivery abstraction exercised with fakes; live Bot API test pending |
| Usage commit/release | Complete | `backend/usage/service.py`, `backend/workers/tasks.py` | `tests/integration/test_worker_outcomes.py` | Terminal failure releases quota and does not write a commit entry |
| Premium entitlement recheck | Complete | `backend/entitlements/service.py`, `backend/workers/tasks.py` | `tests/integration/test_worker_outcomes.py` | Expired subscription falls back to free profile before cache lookup |
| 24-hour media cleanup | Partial | `backend/workers/tasks.py`, `backend/storage/cache.py` | — | Expiry and size eviction implemented; cleanup tests pending |
| Recovery/idempotency | Partial | `backend/workers/tasks.py` | `tests/integration/test_worker_outcomes.py`, `test_outbox_dispatch.py` | Retry/terminal failure and outbox retry covered; stale-job reconciliation tests pending |
| Security tests | Partial | `backend/platforms/urls.py`, `backend/platforms/adapters/ytdlp.py` | `tests/unit/test_urls.py` | Ingestion DNS guard wired into bot and worker; final extracted URL validated against platform allowlist; controlled egress/DNS-rebinding enforcement still pending |
| Operational limits (OD-06) | Partial | `backend/core/config.py` | `tests/unit/test_config.py` | Approved defaults applied; metadata/download timeout split implemented; tier-specific size/duration enforcement still pending |
| Sponsor placements | Not started — policy approved | — | — | Free users only; one placement per successful download, after delivery; moderation deferred |
| Premium/payment integration | Not started — pricing resolved | — | — | 150 Stars / 30 days and 20/day approved 2026-11-06; billing module not implemented |
| Rewarded ads | Not started — direction resolved | — | — | Bot-managed chat ads; 1 credit per ad. Daily cap and credit expiry proposed, pending approval |
| Sponsor system | Later phase | — | — | — |
| Mini App | Later phase | — | — | — |

## Phase 0 gate results

Commands run on 2026-11-06:

- `uv sync --all-groups` — passed
- `uv run ruff check .` — passed
- `uv run ruff format --check .` — passed
- `uv run mypy backend apps` — passed (20 files)
- `uv run pytest -q` — 9 passed
- `docker compose config` — passed

## Phase 1 gate results

Commands run on 2026-11-06:

- `uv run ruff check .` — passed
- `uv run ruff format --check .` — passed
- `uv run mypy backend apps` — passed (49 files)
- `uv run pytest -q` — 89 passed
- `uv run alembic upgrade head` — applied initial schema
- `docker compose config` — passed

Integration tests require PostgreSQL. Set `TEST_DATABASE_URL` to an isolated database, or allow the suite to create a temporary database on the local `DATABASE_URL` server.

## Extraction hardening gate results

Commands run on 2026-11-06:

- `uv run ruff check .` — passed
- `uv run ruff format --check .` — passed
- `uv run mypy backend apps` — passed (49 files)
- `uv run pytest -q` — 142 passed, 5 skipped (live extraction tests gated; PostgreSQL/Redis running)

Live extraction smoke (metadata, download, FFmpeg preparation) passed for YouTube, TikTok, Instagram and Facebook on 2026-11-06 using `tests/integration/test_live_extraction.py`. YouTube required adding `yt-dlp-ejs` (Deno 2.3+ runtime) for JavaScript challenge solving.

| Platform | Live metadata | Live download + prepare | Notes |
|---|---|---|---|
| YouTube | Pass | Pass | Requires `yt-dlp-ejs` + Deno |
| TikTok | Pass | Pass | Portrait 540p downscaled to 480p |
| Instagram | Pass | Pass | Silent reel path exercised |
| Facebook | Pass | Pass | Older sample URLs may hit yt-dlp extractor limits |

## v0 bot gate results (2026-11-09)

- `uv run ruff check .` — passed
- `uv run ruff format --check .` — passed
- `uv run mypy backend apps` — passed (59 files)
- `uv run pytest -q` — 168 passed, 17 skipped (PostgreSQL unavailable locally; live extraction gated)
- Application build smoke test with a dummy token — handlers and engine wired
- `uv run svdb-bot-v0-setup` — bot name, descriptions, command menu and profile photo applied
- Profile verified through `getMyName`, `getMyShortDescription` and `getMyCommands`

The v0 bot was not exercised against the live Bot API for media delivery. It has no durable
usage ledger and must not be treated as production-ready.

## Next task

Extraction is working end to end across YouTube, TikTok, Instagram and Facebook. Next: enforce tier-specific size/duration limits, add Telegram delivery error-mapping tests, cache eviction and stale-job reconciliation tests, and handler tests. Consider controlled egress for full DNS-rebinding protection. Reward daily cap and credit expiry remain open; everything else is approved.
