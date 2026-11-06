# Coding Agent Kickoff — SocialsVideoDownloaderBot

You are the lead backend engineer implementing **SocialsVideoDownloaderBot**. Read `AGENTS.md` and every document in `docs/` before coding. Treat this specification pack as the approved baseline.

## First task: repository reconnaissance

1. Inspect the existing repository, git status, files, runtime and any prior implementation.
2. Do not overwrite or discard existing work.
3. Compare existing code/docs against this pack and report conflicts.
4. Identify which unresolved decisions in `docs/09-open-decisions.md` block the first vertical slice. Do not ask about choices that are already locked.
5. Return a short plan, proposed repository tree and risk list before substantial implementation.

## Product

Build a Telegram bot that accepts supported public video URLs from TikTok, Instagram, YouTube and Facebook, extracts media through yt-dlp adapters, selects the highest eligible quality automatically, processes with FFmpeg when needed, and sends the result directly to Telegram.

Public content only. Do not implement private-content access, authentication bypass, cookie/password collection, DRM circumvention, arbitrary URL fetching or external download links.

## Locked stack

Python modular monolith; `python-telegram-bot`; FastAPI; yt-dlp; FFmpeg/FFprobe; PostgreSQL; Redis + ARQ; SQLAlchemy 2.x async + asyncpg; Alembic; Pydantic + pydantic-settings; pytest/pytest-asyncio/pytest-cov; Ruff; Docker Compose; `uv`.

## Locked decisions

- Telegram-only identity.
- Daily quota period resets at `00:00 Africa/Lagos`.
- Consume included daily allowance before rewarded credits.
- Subscription access is valid through `paid_through`; expire only after that boundary.
- Server-side media retention is 24 hours.
- UUID internal IDs; Telegram IDs BIGINT; UTC timestamps.
- Append-only usage/reward/payment ledgers.
- Transactional outbox for DB-to-Redis dispatch.
- Free plan: 5 successful downloads per Lagos calendar day; maximum 480p.
- Premium: monthly subscription initially paid with Telegram Stars; supports up to 4K where available and priority processing; exact daily allowance and price remain unresolved.
- No own sponsor placements for Premium; free users may receive bot-managed sponsor placements.
- Reward credits are earned only after server-verified rewarded-ad completion.

## Implementation sequence

### Phase 0 — Audit and skeleton
- Inspect repository and report current state.
- Establish `pyproject.toml`, `uv` workflow, settings, logging, package layout, Docker Compose, health endpoint, PostgreSQL and Redis connectivity.
- Add CI-friendly Ruff and pytest configuration.
- Provide `.env.example`; never add real secrets.

### Phase 1 — Core vertical slice
- Telegram `/start` and URL intake.
- URL normalization and strict host/redirect validation.
- Platform registry and extractor adapter interface.
- Persistent user and download job records.
- Entitlement resolution for free plan.
- Atomic quota reservation, commit after successful Telegram delivery, release on definitive failure.
- Transactional outbox and ARQ worker.
- yt-dlp extraction, automatic 360p/480p selection for free users, FFmpeg processing/verification, Telegram delivery.
- 24-hour media cache/retention and guaranteed temporary-workspace cleanup.
- User-safe error messages and structured operational logs.

### Phase 2 — Reliability and hardening
- Retry policy, idempotency, stale-job recovery, outbox dispatcher, worker shutdown.
- SSRF/redirect/DNS-rebinding defenses; subprocess and filesystem isolation.
- Concurrency tests for quota reservations and duplicate updates.
- PostgreSQL/Redis integration tests and Telegram mocks.

### Phase 3 — Monetization foundations (provider integration gated)
- Subscription/payment domain records and verified Telegram Stars payment flow.
- `paid_through` entitlement calculation and renewal/expiry/refund handling.
- Reward session and immutable reward ledger abstractions.
- Do not enable rewarded credits until an ad provider and verification contract are selected.
- Do not invent Premium allowance or pricing; keep configuration unset and prevent purchase UI from advertising an unknown price.

### Phase 4 — Later Mini App
- React + TypeScript only when the rewarded-ad flow requires it.
- Validate Telegram Mini App `initData` server-side.
- Never trust client-side reward claims.

## Mandatory acceptance conditions

- A successful download is charged exactly once, after Telegram delivery succeeds.
- Failed/rejected jobs do not consume successful-download allowance.
- Concurrent requests cannot overspend included allowance or reward credits.
- Daily allowance period uses `Africa/Lagos` calendar boundaries, including DST-safe timezone handling (even though Lagos currently has no DST).
- Rewarded credits are consumed only after included allowance is exhausted.
- Payment/reward callbacks are authenticated, replay-protected and idempotent.
- `paid_through` is evaluated consistently in UTC.
- Media files are removed after 24 hours; per-job temporary workspaces are removed on completion/failure.
- Unauthorized/private URLs and internal-network destinations are rejected.
- Bot/API/worker can restart without silently losing committed jobs.
- No secrets or sensitive URLs appear in logs.

## Deliverables

1. Working repository with documented run instructions.
2. Alembic migrations and `.env.example`.
3. Docker Compose for local development.
4. Unit, integration and relevant end-to-end tests.
5. `docs/implementation-status.md` mapping each requirement to code/tests/status.
6. A final report listing changed files, commands/tests run, results, unresolved decisions and exact next steps.

Do not attempt to implement the entire roadmap in one unreviewed change. Start with reconnaissance and a small, testable vertical slice.
