# SocialsVideoDownloaderBot — Backend Specification Pack

**Status:** Approved implementation baseline / pre-coding  
**Generated:** 2026-11-06  
**Purpose:** Single implementation reference for the first backend build.

## Read first

1. `KICKOFF_PROMPT.md` — give this to the coding agent.
2. `AGENTS.md` — repository-wide engineering rules.
3. `docs/01-product-and-architecture.md`
4. `docs/02-database-specification.md`
5. `docs/03-api-and-telegram-contracts.md`
6. `docs/04-download-pipeline.md`
7. `docs/05-entitlements-and-monetization.md`
8. `docs/06-security-and-privacy.md`
9. `docs/07-operations-and-deployment.md`
10. `docs/08-testing-and-acceptance.md`
11. `docs/09-open-decisions.md`

## Scope

MVP platforms: TikTok public videos; Instagram public Reels, video posts and carousel videos; YouTube public videos and Shorts; Facebook public video posts and Reels.

The product accepts supported public URLs, automatically selects the best permitted quality, and delivers media directly in Telegram. No external download links, private-content access, credential collection, authentication bypass or DRM circumvention.

## Locked technology baseline

- Python modular monolith
- `python-telegram-bot` for Telegram
- FastAPI for HTTP endpoints
- yt-dlp behind platform/extractor adapters
- FFmpeg and FFprobe for media processing/validation
- PostgreSQL as authoritative persistence
- Redis + ARQ for background jobs and coordination
- SQLAlchemy 2.x async + asyncpg
- Alembic migrations
- Pydantic + pydantic-settings
- pytest, pytest-asyncio, pytest-cov, Ruff
- Docker Compose
- `uv` for Python dependency/environment management

## Locked business/database decisions

- Telegram-only user identity; Telegram user ID is the external identity.
- Daily quota resets at midnight in `Africa/Lagos`.
- Consume included allowance before rewarded-ad credits.
- Paid access remains active through the recorded `paid_through` instant/date; access expires after it.
- Server-side media retention: 24 hours.
- UUID internal identifiers; Telegram IDs use BIGINT; timestamps stored in UTC.
- Usage, reward and payment ledgers are append-only.
- Use a transactional outbox for reliable queue dispatch.

## Important unresolved values

Do not invent or silently hardcode Premium allowance/pricing, reward-credit expiry, ad provider, daily reward cap, or free-tier file-size/duration/concurrency ceilings. Keep these configurable and mark the relevant feature as blocked or disabled until product decisions are supplied. See `docs/09-open-decisions.md`.

## Implementation rule

Build a working vertical slice first: `/start` → URL intake → validation → entitlement/quota reservation → queued extraction → format selection → processing → Telegram delivery → usage commit → cleanup. Keep payment, rewarded-ad provider integration and Mini App work behind clean interfaces and feature flags; do not fake provider integrations.
