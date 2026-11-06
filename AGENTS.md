# Agent Instructions — SocialsVideoDownloaderBot

## Mission

Build the project described in the product, architecture, security and engineering documents. Treat this repository documentation as the current specification, while escalating contradictions and unresolved decisions rather than guessing.

## Required reading

Before changing code, read:

0. `backend_specs/` — the approved implementation baseline. Where it conflicts with `docs/`, `backend_specs/` wins. Do not guess items listed in `backend_specs/docs/09-open-decisions.md`.
1. `README.md`
2. `docs/product/product-requirements.md`
3. `docs/product/platform-support.md`
4. `docs/product/freemium-and-entitlements.md`
5. `docs/architecture/architecture-decisions.md`
6. `docs/architecture/system-architecture.md`
7. `docs/architecture/database-design.md`
8. `docs/architecture/security-architecture.md`
9. `docs/engineering/development-standards.md`
10. `docs/operations/deployment-and-operations.md`
11. `docs/project/unresolved-decisions.md`

## Non-negotiable constraints

- MVP supports TikTok, Instagram, YouTube and Facebook only.
- Public content only. Never request or extract users' social-platform passwords, session cookies, browser profiles or private account tokens.
- Do not bypass private-account restrictions, access controls, DRM, paywalls or platform restrictions.
- No arbitrary direct-file URL downloader in MVP.
- No playlists, channels, live streams, batch jobs or non-Telegram delivery in MVP.
- PostgreSQL is the durable source of truth. Redis is not an authoritative ledger.
- Keep the system a modular monolith. Do not split into microservices without an approved architecture decision.
- Keep platform extraction behind an interface; yt-dlp is an adapter, not a domain dependency.
- Never trust client-submitted plan, quota, payment or rewarded-ad state.
- A download counts against quota only after successful Telegram delivery.
- Make handlers, jobs, payment events and reward events idempotent.
- Do not log bot tokens, payment secrets, full sensitive URLs, authorization headers or user-provided credentials.
- Do not claim production readiness until security, operational and policy checks are complete.

## Implementation workflow

1. Inspect the existing repository before creating or replacing files.
2. Report the proposed file plan and any conflicts.
3. Implement one vertical slice at a time.
4. Add migrations and tests with each persistent feature.
5. Run formatting, linting, type checks (if configured), unit tests and relevant integration tests.
6. Update documentation when behavior or decisions change.
7. Summarize changed files, commands run, test results, limitations and unresolved items.

## Required quality gates

- Unit tests for domain policies and entitlement calculations.
- Integration tests for database transactions, outbox publishing, queue processing and delivery outcomes.
- Tests for duplicate Telegram updates, duplicate payment callbacks and duplicate reward callbacks.
- Tests proving failed delivery releases/resolves quota reservation and does not count as a successful download.
- SSRF and redirect validation tests for URL ingestion and extractor networking.
- Tests for temporary-file cleanup and resource limits.
- Tests proving Premium entitlement is rechecked on cache hits.
- No secrets in repository, logs, test snapshots or generated docs.

## Decision handling

If a decision is marked OPEN/PROPOSED/VERIFY in `backend_specs/docs/09-open-decisions.md` or `docs/`, do not invent a final value. Use configuration or a clearly named temporary default only when necessary for local development, and document it. Ask the project owner to approve production values. Decisions already locked by `backend_specs/` (for example `Africa/Lagos` quota periods, 480p free ceiling and 24-hour media retention) must not be reopened without explicit owner instruction.

## Agent output format

For each task, provide:
- Summary
- Files changed
- Design decisions
- Tests executed and results
- Security implications
- Known limitations
- Decisions requiring owner approval
