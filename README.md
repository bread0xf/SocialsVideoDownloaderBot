# SocialsVideoDownloaderBot

A Telegram bot for downloading publicly accessible videos from supported social platforms and delivering them to users in Telegram.

## Product snapshot

- **MVP platforms:** TikTok, Instagram, YouTube, Facebook
- **Access policy:** Public content only; no login, private-content access, DRM circumvention, or access-control bypass
- **Delivery:** Telegram
- **Commercial model:** Freemium + monthly Premium
- **Free allowance:** 5 successful downloads per `Africa/Lagos` calendar day
- **Premium allowance:** 20 successful downloads per `Africa/Lagos` calendar day, 150 Telegram Stars per 30-day month
- **Rewarded allowance:** 1 additional download per verified ad event, delivered as a bot-managed chat ad (daily cap and expiry pending)
- **Free quality:** 480p ceiling (locked)
- **Premium quality:** Best supported source quality, up to 4K where source, processing, Telegram and deployment limits allow
- **Architecture:** Python modular monolith, deployed as separate bot/API/worker/scheduler processes from one codebase

## Locked stack

Python, `python-telegram-bot`, FastAPI, yt-dlp behind a replaceable extraction interface, FFmpeg/FFprobe, PostgreSQL, Redis, ARQ, SQLAlchemy 2.x async, Pydantic Settings, Alembic, pytest, Ruff and Docker Compose, managed with `uv`.

## Repository map

```text
.
├── AGENTS.md
├── README.md
├── backend_specs/          # Approved implementation baseline
├── apps/
│   └── bot/                # Telegram adapter
├── backend/
│   ├── api/                # FastAPI and health/platform endpoints
│   ├── core/               # Settings, logging, quota and error types
│   ├── database/           # Engine, sessions, ORM models
│   ├── delivery/           # Telegram delivery abstraction
│   ├── downloads/          # Submission, state machine, outbox, cache keys
│   ├── entitlements/       # Free/Premium entitlement resolution
│   ├── media/              # Format selection, FFprobe, FFmpeg, cache metadata
│   ├── platforms/          # URL validation, registry, yt-dlp adapter
│   ├── storage/            # Workspaces and cached media files
│   ├── usage/              # Quota reservation, commit, release, ledger
│   └── workers/            # ARQ worker and tasks
├── migrations/             # Alembic
├── tests/                  # Unit/integration tests
└── docs/                   # Older split spec (kept for reference)
```

## Current status

Phase 0 skeleton and the Phase 1 free-tier download slice are implemented: URL validation and platform registry, user/job persistence, entitlement resolution, atomic quota reservation with ledger entries, transactional outbox to ARQ, yt-dlp/FFmpeg processing, Telegram delivery, cache lookup, and expiry/size cleanup tasks.

Remaining hardening work is tracked in `docs/implementation-status.md`: real extractor/media fixture tests, live Telegram delivery tests, cache-cleanup and stale-job tests, and extractor redirect/SSRF validation. Premium pricing and allowance are approved; billing, rewarded ads and sponsor features are not implemented yet.

For a temporary implementation handoff, see `docs/agent-handoff.md`.

`backend_specs/` is the implementation baseline; where `docs/` conflicts with it, `backend_specs/` wins.

## Getting started

Requirements: Python 3.13, `uv`, Docker + Docker Compose, FFmpeg/FFprobe.

```bash
cp .env.example .env
# Set TELEGRAM_BOT_TOKEN in .env

docker compose up -d postgres redis
uv sync --all-groups
uv run alembic upgrade head
uv run svdb-api       # http://localhost:8000/health/live
uv run svdb-bot       # Telegram polling
uv run svdb-worker    # ARQ worker
```

Run quality gates:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy backend apps
uv run pytest
```

Integration tests use PostgreSQL. Set `TEST_DATABASE_URL` to an isolated database, or let the suite create a temporary database on the configured local server.

1. Read `AGENTS.md` and `backend_specs/`.
2. Resolve release-blocking decisions before production launch.
3. Implement in small vertical slices with tests and migrations.

## Important boundary

The bot must only process content that is publicly accessible through supported platform mechanisms. Platform terms, copyright rules, local law, and Telegram policies must be reviewed before launch. A technically downloadable URL is not, by itself, proof that the content may lawfully be downloaded or redistributed.

## Document status

`backend_specs/` defines the locked MVP baseline. Values marked **OPEN** or **VERIFY** in `backend_specs/docs/09-open-decisions.md` still require owner confirmation. Do not silently convert them into settled product requirements.
