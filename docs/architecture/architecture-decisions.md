# Architecture Decision Records

This document captures current project-level decisions. Status labels distinguish decisions from proposals. `backend_specs/` remains the frozen baseline; this register records how the implemented system meets it.

## ADR-001 — Modular monolith

**Status:** Accepted; implemented

Use one Python codebase with clear modules. Run bot, API and worker as separate processes/containers from the same image. There is no separate scheduler: ARQ cron jobs inside the worker handle outbox dispatch, cache cleanup and stale-job reconciliation. Do not introduce microservices for the MVP.

## ADR-002 — Telegram as the delivery channel

**Status:** Accepted; implemented

All MVP downloads are delivered to the user's Telegram chat. No external delivery destinations.

## ADR-003 — Public content only

**Status:** Accepted; implemented

Do not authenticate to social accounts, collect cookies, access private content, bypass access controls or circumvent DRM.

## ADR-004 — Replaceable extraction adapter

**Status:** Accepted; implemented

Use yt-dlp behind a project-owned interface (`backend/platforms/adapters/ytdlp.py`). Platform extraction details stay out of application/domain logic.

## ADR-005 — PostgreSQL is authoritative

**Status:** Accepted; implemented for current tables

PostgreSQL stores users, plans, subscriptions, jobs, quota reservations and ledger entries, cache metadata and outbox events. Redis is transient infrastructure only. Billing, reward and sponsor tables are specified but not implemented.

## ADR-006 — Redis + ARQ for asynchronous work

**Status:** Accepted; implemented

Redis and ARQ execute background jobs and cron maintenance. Job intent and the outbox event are persisted in PostgreSQL before queue publication.

## ADR-007 — Quota committed after delivery

**Status:** Accepted; implemented

Reserve quota during authorization; commit only after successful Telegram delivery. Release the reservation on terminal failure.

## ADR-008 — Freemium and monthly Premium

**Status:** Accepted; pricing resolved 2026-11-06

Free: 5 successful downloads per `Africa/Lagos` day at up to 480p. Premium: 20 successful downloads per day, 150 Telegram Stars per 30-day period, best available quality up to 4K subject to delivery limits. Quota and entitlement resolution are implemented; billing is not.

## ADR-009 — Cache media and Telegram file identifiers

**Status:** Accepted; implemented

Cache processed media with a 24-hour maximum retention and a configured byte cap. Cache keys include normalized source identity, output profile and processing version. Recheck entitlement before every cache delivery and reuse Telegram `file_id` where valid.

## ADR-010 — No Mini App in MVP

**Status:** Accepted

Keep the architecture compatible with a future Telegram Mini App, but ship the bot interface first.

## ADR-011 — Container deployment

**Status:** Accepted; Compose implemented, hosted dev on Railway

Use one Docker image and Compose for local development and initial deployment. The hosted development environment runs the same image as separate Railway services (API, bot, worker) with managed Postgres and Redis. Revisit orchestration only when scale or availability needs justify it.

## ADR-012 — Quality profile

**Status:** Accepted; implemented for the Free ceiling

Free output is capped at 480p. Premium may access higher available qualities up to 4K, subject to practical delivery constraints. Quality selection is automatic; users do not select formats in the MVP.

## ADR-013 — Railway for the hosted development environment

**Status:** Accepted for development only

Use Railway for the development environment because it runs long-lived polling and worker processes, includes ffmpeg/ffprobe/Deno in the project image, supports a persistent worker volume, and allows 15–30 minute jobs. Vercel was rejected: it cannot run long-lived processes, has no persistent disk or system media binaries, and its function duration limits conflict with the extraction and job timeouts.

This does not choose a production host. Production hosting (D-12) and webhook versus polling (D-13) remain open.

## ADR-014 — Documentation layering

**Status:** Accepted

`backend_specs/` is the frozen approved baseline and wins conflicts. `docs/` is the living documentation set: `docs/implementation-status.md` is the single status tracker, architecture and operations docs describe implemented behavior, and decision registers record owner-approved values. Do not edit frozen specifications without owner approval as an erratum.
