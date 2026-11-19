# Implementation Status

> **Authority:** `backend_specs/` is the approved implementation baseline and wins any conflict with this file. This document is the only tracker for what is actually implemented. Do not mark an item complete without code and test references.
>
> **Last reviewed:** 2026-11-17.

## Current state

The free-tier pipeline and the standalone v0 bot are implemented. Extraction has been live-verified for public YouTube, TikTok, Instagram and Facebook videos. Telegram delivery is live-confirmed, including title/uploader captions and ID-based filenames; automated live delivery tests are still pending. The system is **not production-ready**: billing and sponsors do not exist, and controlled egress and tier-specific size/duration enforcement are incomplete. Adsun ad serving and reward credit granting are implemented behind a disabled feature flag.

The Railway development environment (API + bot + worker + managed Postgres/Redis) is deployed and serving; its status is recorded under [Deployed environments](#deployed-environments).

## Requirement status

| Capability | Status | Code | Tests | Notes |
|---|---|---|---|---|
| Repository reconnaissance | Implemented | `README.md`, `backend_specs/` | — | Conflicts reconciled: Lagos quota, 480p free ceiling, 24h retention |
| Configuration, logging, runtime skeleton | Implemented | `backend/core/config.py`, `backend/core/logging.py` | `tests/unit/test_config.py`, `tests/unit/test_logging.py` | Fail-fast production token check; locked defaults |
| Compose topology and health endpoints | Implemented | `compose.yaml`, `Dockerfile`, `backend/api/` | `tests/unit/test_health.py` | `/health/live` tested; `/health/ready` verified on Railway against live Postgres/Redis |
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
| Rewarded ad serving (Adsun) | Implemented, disabled by default | `backend/ads/`, `apps/bot/main.py` | `tests/unit/test_adsun_provider.py`, `tests/unit/test_bot_reward.py` | `/reward` and a quota-exhausted button serve an ad with HTML parse mode and `protect_content`; no-fill/provider errors fall back safely; `ADSUN_ENABLED=false` by default. Token never logged |
| Reward credit granting | Implemented, disabled by default | `backend/rewards/`, `backend/api/routes/rewards.py`, `backend/usage/service.py` | `tests/integration/test_rewards.py`, `tests/unit/test_api_rewards.py`, `tests/unit/test_reward_policy.py` | `GET /api/v1/rewards/adsun/callback` verifies the shared secret in constant time, requires an ASCII user id, a normalised configured block and a fresh timestamp, and records each event in `reward_events` before granting. Grants are `usage_ledger` rows (`entry_type=reward_granted`) consumed through `usage_reservations.reward_ledger_id`. A callback can only redeem a pending served-ad session; otherwise it returns `no_session` and grants nothing. Adsun test probes (`test=1` or `test=true`) are acknowledged with `{"status":"test"}` after secret verification and write nothing: no `reward_events` claim, no session redemption and no credit. The temporary capture route treats them the same while still logging parameter names and values. Neutral aliases `/api/v1/hooks/r1/cb` and `/api/v1/hooks/r1/probe` mount the same handler objects for Adsun's panel, which rejects paths containing `rewards/adsun`; they are hidden from OpenAPI and keep identical guards. Security review added block-form-stable idempotency keys, aware-datetime guards, bounded timestamp parsing, no-store responses, debug-level unconfigured probes, and error logs that omit tracebacks and exception text. Cap/expiry/premium defaults are D-05/D-06/D-07 proposals, not approvals. Uvicorn access logs are disabled because the secret is in the query string |
| Reward ad sessions (Adsun cooldown) | Implemented, disabled by default | `backend/rewards/service.py`, `backend/database/models.py`, `apps/bot/main.py`, `backend/workers/` | `tests/integration/test_rewards.py`, `tests/unit/test_bot_reward.py` | Before opening a session the bot runs the same advisory eligibility checks as `grant_reward` (blocked, Premium per `REWARD_PREMIUM_ELIGIBLE`, Lagos-day cap including released credits). Ineligible users get a short reason (cap message includes the Africa/Lagos midnight reset) and no session row, and the provider is not called. The bot then creates a `reward_sessions` row before fetching an ad. A second request while one is pending replies "finish the current ad" and does not call the provider. The callback re-runs every check and redeems the pending session in the same transaction as the grant under the per-user advisory lock; expired sessions never redeem. A worker cron expires stale sessions. Structured logs record session created/reused/redeemed/expired, ad skips by reason, and callback `no_session` counters |
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
| 2026-11-17 | Adsun ad serving | Ruff and format passed; mypy passed (63 files); 205 passed, 17 skipped (PostgreSQL and live-extraction tests gated); `adsun[ptb]` added and locked |
| 2026-11-17 | Adsun reward credit granting | Ruff and format passed; mypy passed (68 files); 246 passed, 5 skipped with PostgreSQL available (live-extraction gated); migration `8b2f4c1d9e70` applied, `alembic check` clean, downgrade/upgrade round-trip verified |
| 2026-11-17 | Adsun reward security review | Ruff and format passed; mypy passed (69 files); 274 passed, 5 skipped with PostgreSQL available (live-extraction gated). New tests cover concurrent same-event claims, concurrent distinct events at the cap, concurrent commit/release settlement, Lagos-midnight cap reset, no UTC-midnight reset, expired-credit reservation refusal, prefixed-block dedupe, released-credit cap accounting, modified-timestamp replay bound, timestamp overflow, no-traceback error logging and `Cache-Control: no-store`. Migration round-trip re-verified |
| 2026-11-18 | Adsun reward sessions (ad cooldown) | Ruff and format passed; mypy passed (69 files); 283 passed, 5 skipped with PostgreSQL available (live-extraction gated; 24 of them in `tests/integration/test_rewards.py`). Tests cover valid redeem, replay with a new timestamp returning `no_session`, forged callbacks without a session, an old replay that must not consume a newer session, expired sessions, concurrent callbacks for one session, pending-session cooldown on a new fetch, TTL cleanup, and the existing cap/expiry/Premium rules. Migration `d1c9a7b3e5f2` applied, `alembic check` clean, and a downgrade/upgrade round-trip with a `no_session` probe row verified |
| 2026-11-18 | Adsun reward eligibility pre-check | Ruff and format passed; mypy passed (69 files); 289 passed, 5 skipped with PostgreSQL available (live-extraction gated; 27 of them in `tests/integration/test_rewards.py`). Bot tests cover capped, Premium-ineligible and blocked users: no provider call, a short reply (the cap reply names the Africa/Lagos midnight), and no session row. Integration tests call `open_reward_ad_session` against PostgreSQL and assert zero `reward_sessions` rows for blocked and Premium users and no new pending row for a capped user. Callback-side checks are unchanged and remain authoritative. `alembic check` clean on a fresh database |
| 2026-11-18 | Adsun staging capture probe (temporary) | Ruff and format passed; mypy passed (69 files); 293 passed, 5 skipped with PostgreSQL available. `GET /api/v1/rewards/adsun/capture` verifies the callback secret, logs parameter names and non-secret values plus receive time, returns 500 on the first authenticated call per `(userid, block)` and 200 on retries, and is gated by `ADSUN_CAPTURE_ENABLED=false` plus an `APP_ENV=production` refusal. Unit tests cover the default-off gate, production refusal, bad secret, logging/redaction and per-pair retry behaviour. Must be removed before production (Known gaps #11). `alembic check` clean on a fresh database |
| 2026-11-18 | Adsun test callbacks | Ruff and format passed; mypy passed (69 files); 300 passed, 5 skipped with PostgreSQL available. `test=1`/`test=true` callbacks return `200` with `{"status":"test"}` and `Cache-Control: no-store` after secret verification, without parsing the payload, inserting a `reward_events` claim, redeeming a pending `reward_sessions` row or writing `usage_ledger`. Tests cover `1`/`true`, a bad secret returning `403`, the capture route still logging params and values including `test` while bypassing its first-call 500, a normal callback still granting, and a pending session left untouched. `alembic check` clean on a fresh database |
| 2026-11-19 | Adsun neutral-path aliases | Ruff and format passed; mypy passed (69 files); 313 passed, 5 skipped with PostgreSQL available. `GET /api/v1/hooks/r1/cb` and `GET /api/v1/hooks/r1/probe` mount the same handler objects as the original callback and capture routes (asserted by identity), stay out of the OpenAPI schema, and keep every guard: bad secret `403` with `no-store`, disabled `404`, capture production refusal, `test=1` returning `{"status":"test"}` without writes, and capture `500`→`200` per pair without a test call consuming the first-call state. The DB-backed valid-callback and test-callback tests run against both paths. Original `/api/v1/rewards/adsun/*` paths remain active. No schema change; `alembic check` clean |

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
| Railway development | Full stack live; delivery verified | API healthy at `https://socialsvideodownloaderbot-production.up.railway.app`; both migrations applied; bot polling and worker cron running; live video delivery confirmed 2026-11-10. Runbook in `docs/operations/railway-dev-environment.md` |
| Production | Not deployed | Hosting decision D-12 remains open; see `docs/project/unresolved-decisions.md` |

## Known gaps and next work

1. Enforce tier-specific size, duration and concurrency limits.
2. Add automated live Telegram delivery tests and map Bot API errors.
3. Add cache-eviction and stale-job reconciliation tests.
4. Add handler tests for `apps/bot` `/start`, `/help`, `/status` and URL intake.
5. Add controlled egress or network policy for full DNS-rebinding protection.
6. Implement billing and sponsor placements according to `backend_specs/docs/05`; the Adsun ad-serving and reward-credit halves are done and must stay flag-disabled until the open decisions and provider contract are approved.
7. Approve the reward daily cap, credit expiry and Premium eligibility (D-05, D-06, D-07); current values are configuration defaults from `docs/adsun-plan.md`, not approvals.
8. Add a reward-granted notification/outbox event and a credit-expiry worker job; today expired credits are merely excluded from the balance.
9. Fix role-specific production configuration validation before any production deployment: today `APP_ENV=production` requires a Telegram token for every process, including the API.
10. Reward callback residual risks: the shared secret is static and travels in the query string, so a leak lets an attacker redeem any user's currently pending ad session (at most one per user, provider and block) and still bounds minting by `REWARD_DAILY_CAP` per Lagos day. A callback with no pending session returns `no_session`, so a replayed old timestamp cannot mint by itself. There is no per-secret rate limit or alerting yet. The callback idempotency key is second-resolution, so two genuine completions in the same second collapse into one grant. Rotate `ADSUN_REWARD_SECRET` after any suspected exposure and exclude the query string from any proxy or error-capture integration.
11. **Remove before production:** `GET /api/v1/rewards/adsun/capture` and its neutral alias `GET /api/v1/hooks/r1/probe` are temporary staging-only debug routes gated by `ADSUN_CAPTURE_ENABLED=false` (also hidden when `APP_ENV=production`). They verify the callback secret, log parameter names plus non-secret values and receive time, and fail the first call per `(userid, block)` to observe Adsun retries. Delete the routes, their config flag, their tests and the `.env.example` entry before any production deployment; they must not ship enabled. The first-call state is process-local, so a restart or multiple API workers can repeat the 500.

## Decisions

Approved product and operational values live in `backend_specs/docs/09-open-decisions.md` and `docs/project/unresolved-decisions.md`. Stale text in `backend_specs/docs/02-database-specification.md` and `backend_specs/KICKOFF_PROMPT.md` about Premium pricing is superseded by `docs/09`; do not edit frozen specifications without owner approval as an erratum.
