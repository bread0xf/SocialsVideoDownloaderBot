# Implementation Status

> Updated as implementation proceeds. Do not mark an item complete without pointing to code and tests.

| Requirement | Status | Code reference | Test reference | Notes |
|---|---|---|---|---|
| Repository reconnaissance | Complete | `README.md`, `backend_specs/` | — | Conflicts reconciled: Lagos quota, 480p free, 24h retention |
| Runtime/config/logging skeleton | Complete | `backend/core/config.py`, `backend/core/logging.py`, `pyproject.toml` | `tests/unit/test_config.py` | Fail-fast production token check; locked defaults |
| Docker Compose + health checks | Complete | `compose.yaml`, `Dockerfile`, `backend/api/app.py`, `backend/api/routes/health.py` | `tests/unit/test_health.py` | `/health/live` tested; `/health/ready` needs live DB/Redis |
| Alembic schema | Complete | `alembic.ini`, `migrations/env.py`, `migrations/versions/71cd52ac280f_initial_schema.py` | Integration fixtures create the current metadata | Initial schema plus seeded free/premium plans and MVP platform registry |
| Telegram `/start`, `/help`, `/status` | Partial | `apps/bot/main.py` | — | Handlers implemented; handler tests still pending |
| URL validation/platform registry | Complete | `backend/platforms/urls.py`, `backend/platforms/registry.py` | `tests/unit/test_urls.py`, `tests/unit/test_registry.py` | Canonicalization, port/credential/IP/localhost blocking, DNS-global-address guard |
| Persistent download jobs | Complete | `backend/database/models.py`, `backend/downloads/service.py` | `tests/integration/test_download_submission.py` | Idempotent submission, active-job limit, outbox event |
| Atomic quota reservation | Complete | `backend/usage/service.py` | `tests/integration/test_usage_quota.py` | Advisory lock, reserve/commit/release, append-only ledger entries |
| Transactional outbox + ARQ | Complete | `backend/downloads/outbox.py`, `backend/workers/tasks.py` | `tests/integration/test_outbox_dispatch.py` | Publishes each event once; failed enqueue remains retryable |
| yt-dlp adapter | Partial | `backend/platforms/adapters/ytdlp.py` | — | Subprocess isolation/timeouts/output caps implemented; real-extractor tests pending |
| Automatic format selection | Complete | `backend/media/selection.py` | `tests/unit/test_format_selection.py` | Plan-height ceiling, H.264/AAC preference, combined vs separate streams, size checks |
| FFmpeg/FFprobe validation | Partial | `backend/media/ffprobe.py`, `backend/media/processing.py` | Worker tests mock probe | Real media fixture tests pending |
| Telegram media delivery | Partial | `backend/delivery/telegram.py`, `backend/workers/tasks.py` | `tests/integration/test_worker_outcomes.py` | Delivery abstraction exercised with fakes; live Bot API test pending |
| Usage commit/release | Complete | `backend/usage/service.py`, `backend/workers/tasks.py` | `tests/integration/test_worker_outcomes.py` | Terminal failure releases quota and does not write a commit entry |
| Premium entitlement recheck | Complete | `backend/entitlements/service.py`, `backend/workers/tasks.py` | `tests/integration/test_worker_outcomes.py` | Expired subscription falls back to free profile before cache lookup |
| 24-hour media cleanup | Partial | `backend/workers/tasks.py`, `backend/storage/cache.py` | — | Expiry and size eviction implemented; cleanup tests pending |
| Recovery/idempotency | Partial | `backend/workers/tasks.py` | `tests/integration/test_worker_outcomes.py`, `test_outbox_dispatch.py` | Retry/terminal failure and outbox retry covered; stale-job reconciliation tests pending |
| Security tests | Partial | `backend/platforms/urls.py`, `backend/platforms/adapters/ytdlp.py` | `tests/unit/test_urls.py` | URL/DNS/SSRF ingestion checks covered; extractor redirect validation tests pending |
| Operational limits (OD-06) | Partial | `backend/core/config.py` | `tests/unit/test_config.py` | Approved defaults applied; tier-specific size/duration enforcement and metadata/download timeout split pending |
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

## Next task

Harden the extraction engine: split metadata and download timeouts, add extractor redirect/SSRF validation, add real yt-dlp fixture tests, and enforce tier-specific size/duration limits. Then continue with FFmpeg fixture tests, Telegram delivery error mapping, cache eviction, stale-job reconciliation and handler tests. Reward daily cap and credit expiry remain open; everything else is approved.
