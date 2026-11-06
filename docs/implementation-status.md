# Implementation Status

> Updated as implementation proceeds. Do not mark an item complete without pointing to code and tests.

| Requirement | Status | Code reference | Test reference | Notes |
|---|---|---|---|---|
| Repository reconnaissance | Complete | `README.md`, `backend_specs/` | — | Conflicts reconciled: Lagos quota, 480p free, 24h retention |
| Runtime/config/logging skeleton | Complete | `backend/core/config.py`, `backend/core/logging.py`, `pyproject.toml` | `tests/unit/test_config.py` | Fail-fast production token check; locked defaults |
| Docker Compose + health checks | Complete | `compose.yaml`, `Dockerfile`, `backend/api/app.py`, `backend/api/routes/health.py` | `tests/unit/test_health.py` | `/health/live` tested; `/health/ready` needs live DB/Redis |
| Alembic schema | In progress | `alembic.ini`, `migrations/env.py` | — | Wiring only; no schema migration yet |
| Telegram `/start` and `/help` | Partial | `apps/bot/main.py` | — | Handlers implemented; handler tests pending |
| URL validation/platform registry | Not started | — | — | Phase 1 |
| Persistent download jobs | Not started | — | — | Phase 1 |
| Atomic quota reservation | Not started | `backend/core/quota.py` | `tests/unit/test_quota_period.py` | Lagos period helper done; reservation/ledger pending |
| Transactional outbox + ARQ | Not started | `backend/workers/` | — | ARQ worker process wired; no job tasks yet |
| yt-dlp adapter | Not started | — | — | Phase 1 |
| Automatic format selection | Not started | — | — | Phase 1 |
| FFmpeg/FFprobe validation | Not started | — | — | Phase 1 |
| Telegram media delivery | Not started | — | — | Phase 1 |
| Usage commit/release | Not started | — | — | Phase 1 |
| 24-hour media cleanup | Not started | — | — | Phase 1 |
| Recovery/idempotency | Not started | — | — | Phase 1/2 |
| Security tests | Not started | — | — | SSRF/redirect/DNS tests in Phase 2 |
| Premium/payment integration | Blocked by OD-01/02 | — | — | Do not implement purchase UI or price |
| Rewarded ads | Blocked by OD-03/04/05 | — | — | Provider interface only until selected |
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

## Next task

Phase 1 vertical slice: URL validation/platform registry, user upsert, job persistence, quota reservation/commit/release, transactional outbox, ARQ job dispatch, yt-dlp adapter, format selection, FFmpeg/FFprobe verification, Telegram delivery, and 24-hour cache cleanup.
