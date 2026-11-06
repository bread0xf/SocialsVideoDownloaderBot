# AGENTS.md — SocialsVideoDownloaderBot

## Authority and conflict resolution

1. User-approved decisions in this repository and this specification pack are authoritative.
2. `docs/09-open-decisions.md` identifies unresolved product choices. Do not guess them.
3. If code, comments, generated migrations or old documents conflict with these specifications, stop and report the conflict before making a destructive change.
4. Do not broaden MVP scope.

## Product boundaries

- Publicly accessible content only.
- MVP platforms: TikTok public videos; Instagram public Reels/video posts/carousel videos; YouTube public videos/Shorts; Facebook public video posts/Reels.
- No private/restricted media, login/session-cookie collection, access-control bypass, DRM circumvention, arbitrary file URL fetching or external download links.
- Deliver through Telegram; video mode where suitable, document fallback where appropriate.
- Quality selection is automatic; users do not select formats in the initial flow.

## Engineering rules

- Python modular monolith. Keep domain/application logic independent from Telegram handlers, FastAPI routes, yt-dlp and ARQ.
- PostgreSQL is the source of truth. Redis is not authoritative for payments, subscriptions, quota balances or rewards.
- Use async SQLAlchemy 2.x and explicit transaction boundaries.
- Use UUID primary keys for internal records. Store Telegram IDs as BIGINT.
- Store instants as timezone-aware UTC timestamps. Convert to `Africa/Lagos` only for daily quota period calculation and presentation.
- Use Alembic for every schema change. Never rely on `create_all()` in production.
- Use append-only ledgers for usage, rewards and payment events. Corrections are compensating entries, not mutation/deletion.
- Use idempotency keys and unique constraints for externally retried operations.
- Use transactional outbox for job dispatch and other DB-to-queue side effects.
- Bot handlers call application services; they must not contain quota, entitlement or payment rules.
- Keep yt-dlp types inside the extraction adapter. Convert results to domain DTOs.
- Never pass user-supplied paths or unrestricted yt-dlp options to subprocesses.
- Every download job gets an isolated workspace and bounded resource/time limits.
- Do not log bot tokens, provider secrets, full sensitive URLs, cookies, or raw payment payloads.
- Add tests with every feature. Test concurrency and failure paths, not only happy paths.
- Use structured logs and stable error codes. Do not expose stack traces or extractor internals to users.
- Pin and validate dependency versions at implementation time; do not invent version pins in docs.
- Keep optional/future integrations out of runtime dependencies until enabled.

## Required workflow

1. Inspect repository and existing documentation before editing.
2. Produce a concise implementation plan and identify unresolved decisions that block work.
3. Implement in small vertical slices.
4. Add/update migrations and tests with each persistence change.
5. Run Ruff, type checks if configured, unit tests and integration tests.
6. Report commands run, outcomes, known gaps and next task.
7. Never claim a feature is implemented unless code and tests demonstrate it.

## Repository hygiene

- Keep `.env` and secrets out of git; maintain `.env.example`.
- Docker Compose must use health checks and persistent volumes where required.
- Provide safe local development defaults; no production secrets or real payment/ad credentials.
- Avoid empty speculative modules. Implement modules as their roadmap phase starts.
