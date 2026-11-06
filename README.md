# SocialsVideoDownloaderBot

A Telegram bot for downloading publicly accessible videos from supported social platforms and delivering them to users in Telegram.

## Product snapshot

- **MVP platforms:** TikTok, Instagram, YouTube, Facebook
- **Access policy:** Public content only; no login, private-content access, DRM circumvention, or access-control bypass
- **Delivery:** Telegram
- **Commercial model:** Freemium + monthly Premium
- **Free allowance:** 5 successful downloads per `Africa/Lagos` calendar day
- **Rewarded allowance:** 1 additional download per successfully verified rewarded-ad event (provider pending)
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
│   ├── api/                # FastAPI and health endpoints
│   ├── core/               # Settings, logging, quota helpers
│   ├── database/           # Engine, sessions, Redis
│   └── workers/            # ARQ worker
├── migrations/             # Alembic
├── tests/                  # Unit/integration tests
└── docs/                   # Older split spec (kept for reference)
```

## Current status

Phase 0 skeleton: configuration, structured logging, PostgreSQL/Redis wiring, health endpoints, ARQ worker, Alembic wiring, Docker Compose, and initial tests. The free downloader vertical slice is next.

`backend_specs/` is the implementation baseline; where `docs/` conflicts with it, `backend_specs/` wins. See `docs/implementation-status.md`.

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
uv run pytest
```

1. Read `AGENTS.md` and `backend_specs/`.
2. Resolve release-blocking decisions before production launch.
3. Implement in small vertical slices with tests and migrations.

## Important boundary

The bot must only process content that is publicly accessible through supported platform mechanisms. Platform terms, copyright rules, local law, and Telegram policies must be reviewed before launch. A technically downloadable URL is not, by itself, proof that the content may lawfully be downloaded or redistributed.

## Document status

`backend_specs/` defines the locked MVP baseline. Values marked **OPEN** or **VERIFY** in `backend_specs/docs/09-open-decisions.md` still require owner confirmation. Do not silently convert them into settled product requirements.
