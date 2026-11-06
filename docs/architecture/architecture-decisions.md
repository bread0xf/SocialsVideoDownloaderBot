# Architecture Decision Records

This document captures current project-level decisions. Status labels distinguish decisions from proposals.

## ADR-001 — Modular monolith

**Status:** Accepted

Use one Python codebase with clear modules. Run bot, API, worker and scheduler as separate processes/containers when operationally useful. Do not introduce microservices for the MVP.

**Reason:** Keeps domain boundaries explicit without premature distributed-system complexity.

## ADR-002 — Telegram as the delivery channel

**Status:** Accepted

All MVP downloads are delivered to the user's Telegram chat. No external delivery destinations.

## ADR-003 — Public content only

**Status:** Accepted

Do not authenticate to social accounts, collect cookies, access private content, bypass access controls or circumvent DRM.

## ADR-004 — Replaceable extraction adapter

**Status:** Accepted

Use yt-dlp behind a project-owned interface. Keep platform-specific extraction details out of application/domain logic.

## ADR-005 — PostgreSQL is authoritative

**Status:** Accepted

PostgreSQL stores durable users, plans, subscriptions, payments, jobs, quota ledger, reward transactions, cache metadata and outbox events. Redis is transient infrastructure only.

## ADR-006 — Redis + ARQ for asynchronous work

**Status:** Proposed/Accepted stack direction

Use Redis and ARQ for background job execution, locks, short-lived coordination and rate limiting. Persist job intent and outbox event in PostgreSQL before queue publication.

## ADR-007 — Quota committed after delivery

**Status:** Accepted

Reserve quota during authorization; commit only after successful Telegram delivery. Release/reconcile on terminal failure.

## ADR-008 — Freemium and monthly Premium

**Status:** Accepted direction; details open

Free allowance is five successful downloads per day. Monthly Premium uses Telegram Stars as the initial proposed payment rail. Price and Premium quota remain unresolved.

## ADR-009 — Cache media and Telegram file identifiers

**Status:** Accepted direction

Use persistent media caching with configurable TTL and storage limits. Cache keys include normalized source identity, output profile and processing version. Telegram `file_id` may be reused where valid.

## ADR-010 — No Mini App in MVP

**Status:** Accepted

Keep the architecture compatible with a future Telegram Mini App, but ship the bot interface first.

## ADR-011 — Docker Compose deployment

**Status:** Proposed

Use Docker Compose for reproducible development and initial deployment. Revisit orchestration only when scale/availability needs justify it.

## ADR-012 — Quality profile

**Status:** Accepted

Free output is capped at 480p. Premium may access higher available qualities up to 4K, subject to practical delivery constraints. Quality selection is automatic; users do not select formats in the MVP.
