# Unresolved Decisions and Approval Register

Do not silently decide these on behalf of the project owner.

> `backend_specs/` is the implementation baseline and supersedes this file on conflict. Decisions recorded as resolved below are locked there or by explicit owner approval and must not be reopened without instruction.

## Open

| ID | Decision | Current direction | Needed before |
|---|---|---|---|
| D-04 | Rewarded-ad delivery mechanism | Bot-managed chat/sponsor message is chosen; single-use server token vs. third-party postback still open | Reward feature |
| D-05 | Reward daily cap | Proposed 10 rewarded downloads per user per Lagos day | Reward feature |
| D-06 | Reward credit expiry | One ad = one extra download; proposed expiry at the end of the Lagos quota day earned | Reward feature |
| D-07 | Premium reward eligibility | Proposed: not eligible, because Premium excludes sponsor placements | Reward feature |
| D-09 | Premium priority semantics | Higher processing priority proposed | Queue implementation |
| D-12 | Production hosting provider and region | Railway is used for development only; production host is not chosen | Production deployment |
| D-13 | Webhook vs long polling | Long polling is implemented for the MVP; webhook mode is not | Bot deployment |
| D-14 | Subscription renewal, cancellation and refund behavior | Telegram Stars lifecycle not defined | Billing release |
| D-15 | Legal/policy basis and takedown process | Review required | Public launch |

## Resolved

| ID | Decision | Chosen value |
|---|---|---|
| D-01 | Free maximum resolution | 480p (locked) |
| D-02 | Premium monthly price | 150 Telegram Stars per 30-day subscription (2026-11-06) |
| D-03 | Premium daily quota | 20 included downloads per `Africa/Lagos` day (2026-11-06) |
| D-08 | Daily quota reset timezone | Local midnight `Africa/Lagos`; timestamps stored in UTC (locked) |
| D-10 | Telegram upload limits | 50 MB cloud Bot API, 48 MiB effective cap; 2000 MB with a local Bot API server |
| D-11 | Cache storage cap | 50 GiB initial cap; 24-hour retention (2026-11-06) |
| D-16 | Reward quantity | One additional download per verified ad (2026-11-06) |
| D-17 | Ad delivery direction | Bot-managed chat/sponsor messages; provider interface remains (2026-11-06) |
| D-18 | Free/Premium operational limits | Free 48 MiB / 600 s / 1 job; Premium 1.9 GB / 1800 s / 2 jobs; worker concurrency 2; approved timeouts |
| D-19 | Sponsor placement policy | Free users only; one placement per successful download, after delivery; no PII or preference tracking (2026-11-06) |
| D-20 | Development hosting | Railway, development only: API + bot + worker + managed Postgres/Redis (2026-11-09) |

## Decision records

### D-02 — Premium price: 150 Stars

- Chosen: 150 Telegram Stars per 30-day subscription.
- Reason: owner decision.
- Impact: invoice amount; Telegram fixes subscription periods at 30 days.
- Follow-up: re-verify Telegram's minimum, maximum (10,000 Stars) and payout terms before billing release.

### D-03 — Premium allowance: 20/day

- Chosen: 20 included successful downloads per `Africa/Lagos` day.
- Reason: owner decision; a published fair-use limit rather than “unlimited”.
- Impact: `premium_daily_limit=20`; entitlement and quota tests use this value.

### D-10 — Telegram upload limits

- Cloud Bot API: 50 MB multipart upload; 20 MB send-by-URL; no limit when resending by `file_id`; 20 MB `getFile` download.
- Local Bot API server (`--local`): 2000 MB upload.
- Recommendation: a cloud-only deployment caps all deliveries at 48 MiB. Premium 4K requires the local Bot API server.
- Oversized media steps down within the plan ceiling, then fails with `FILE_TOO_LARGE`, releases the reservation, and never charges quota or splits files.

### D-11 — Cache storage cap

- Chosen: 50 GiB initial cap; media retention is locked at a maximum of 24 hours.
- Hosted development may use a smaller cap sized below the attached volume.

### D-18 — Free/Premium operational limits

- Chosen: Free 48 MiB / 600 s / 1 concurrent job; Premium 1.9 GB / 1800 s / 2 concurrent jobs; worker concurrency 2; metadata timeout 60 s; download timeout 900 s; FFmpeg timeout 600 s; job timeout 1800 s; job max age 7200 s; cache cap 50 GiB; 3 retry attempts.
- Implementation status: global tier-independent defaults are applied. Tier-specific size, duration and concurrency enforcement is still pending, and Premium delivery above 48 MiB requires a local Bot API server.

### D-19 — Sponsor placement policy

- Chosen: Free users only; exactly one placement per successful download, sent after delivery; no PII or preference tracking; content moderation deferred.
- Impact: emit a placement only after confirmed Telegram delivery; never on failure paths.
- Follow-up: allowed-content and moderation policy; campaign billing and targeting remain open.

### D-20 — Development hosting on Railway

- Chosen: Railway development environment running API, bot and worker from the existing image, with managed Postgres and Redis and a worker media volume.
- Reason: end-to-end Telegram testing and engine timing on reliable disk and bandwidth. Vercel cannot run long-lived polling/worker processes, lacks ffmpeg/Deno and persistent disk, and its function limits conflict with job timeouts.
- Scope: development only, `APP_ENV=development`, single replicas. It does not resolve production hosting (D-12) or webhook mode (D-13).
- Security note: the worker runs with `RAILWAY_RUN_UID=0` so it can write the root-owned volume. This is a development concession, not a production pattern.

## Proposals still open

- Reward cap: 10 rewarded downloads per user per Lagos day (D-05).
- Reward credit expiry: end of the Lagos quota day earned (D-06).
- Premium users cannot earn rewarded credits (D-07).
- Premium processing priority (D-09).

## Decision record format

For each resolved item, record the decision ID and date, chosen value, alternatives considered, reason, user-facing impact, implementation/configuration impact, and tests/documentation updated.
