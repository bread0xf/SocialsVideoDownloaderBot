# Unresolved Decisions and Approval Register

Do not silently decide these on behalf of the project owner.

> `backend_specs/` is the implementation baseline and supersedes this file on conflict. Decisions recorded as resolved below are locked there and must not be reopened without explicit owner instruction.

| ID | Decision | Current direction | Needed before |
|---|---|---|---|
| D-04 | Rewarded-ad delivery mechanism | Partially resolved: bot-managed chat/sponsor ads; Telegram has no official rewarded-ad API. Single-use server token vs. third-party postback still open | Reward feature |
| D-05 | Reward daily cap | Open; proposed 10 rewarded downloads per user per Lagos day | Reward feature |
| D-06 | Reward credit expiry | Partially resolved: one ad = one extra download; proposed expiry at end of the Lagos quota day earned | Reward feature |
| D-07 | Premium reward eligibility | Proposed: not eligible, because Premium excludes sponsor placements | Reward feature |
| D-09 | Premium priority semantics | Higher processing priority proposed | Queue implementation |
| D-11 | Cache storage cap | Resolved 2026-11-06 — 50 GiB initial cap; 24h retention locked | Deployment |
| D-12 | Hosting provider/region | Open | Deployment |
| D-13 | Webhook vs long polling | Open; choose based on deployment | Bot deployment |
| D-14 | Subscription renewal/cancellation/refund behavior | Define Telegram Stars lifecycle | Billing release |
| D-15 | Legal/policy basis and takedown process | Review required | Public launch |

## Resolved decisions

| ID | Decision | Chosen value | Recorded |
|---|---|---|---|
| D-01 | Free maximum resolution | 480p | 2026-11-06 (`backend_specs/`) |
| D-02 | Premium monthly price | 150 Telegram Stars per 30-day subscription | 2026-11-06 (owner) |
| D-03 | Premium daily quota | 20 included downloads per `Africa/Lagos` day | 2026-11-06 (owner) |
| D-08 | Daily quota reset timezone | Local midnight `Africa/Lagos`; persist UTC | 2026-11-06 (`backend_specs/`) |
| D-10 | Telegram upload limits | 50 MB cloud Bot API; 2000 MB with a local Bot API server (`--local`) | 2026-11-06 (verified) |
| D-16 | Reward quantity | One additional download per verified ad | 2026-11-06 (owner) |
| D-17 | Ad delivery direction | Bot-managed chat/sponsor messages; provider interface remains | 2026-11-06 (owner) |
| D-18 | Free/Premium operational limits | Free 48 MiB / 10 min / 1 job; Premium 1.9 GB / 30 min / 2 jobs; worker concurrency 2; approved timeouts | 2026-11-06 (owner) |
| D-19 | Sponsor placement policy | Free users only; one placement per successful download, after delivery; no PII or preference tracking | 2026-11-06 (owner) |

## Decision records

### D-02 — Premium price: 150 Stars

- Chosen: 150 Telegram Stars per 30-day subscription.
- Alternatives considered: none recorded.
- Reason: owner decision.
- User-facing impact: Premium subscription price.
- Implementation/configuration impact: invoice amount; Telegram fixes subscription periods at 30 days.
- Follow-up: re-verify Telegram's current minimum, maximum (10,000 Stars) and payout terms before billing release.

### D-03 — Premium allowance: 20/day

- Chosen: 20 included successful downloads per `Africa/Lagos` day.
- Reason: owner decision; a published fair-use limit rather than “unlimited”.
- Implementation/configuration impact: `premium_daily_limit=20`; plan row may remain nullable and fall back to configuration.
- Tests/documentation: entitlement and quota tests must use this value; this register updated.

### D-10 — Telegram upload limits

- Cloud Bot API: 50 MB upload (multipart), 20 MB send-by-URL, no limit when resending by `file_id`, 20 MB `getFile` download.
- Local Bot API server with `--local`: 2000 MB upload, unlimited download.
- Recommendation: local Bot API server for Premium 4K; a cloud-only deployment must cap all deliveries at 48 MiB.
- Oversized media: step down bitrate/resolution within the plan ceiling, then fail with `FILE_TOO_LARGE`, release the reservation, and never charge quota or split files.

### D-18 — Free/Premium operational limits

- Chosen: free 48 MiB / 600 s / 1 concurrent job; Premium 1.9 GB / 1800 s / 2 concurrent jobs; worker concurrency 2; metadata timeout 60 s; download timeout 900 s; FFmpeg timeout 600 s; job timeout 1800 s; job max age 7200 s; cache cap 50 GiB; 3 retry attempts.
- Reason: stay below Telegram's 50 MB cloud upload ceiling for free, allow 4K Premium with a local Bot API server, and keep CPU/disk usage predictable.
- Implementation/configuration impact: tier-independent defaults are applied now; tier-specific enforcement and the split between metadata and download timeouts remain for the extraction-engine phase.
- Follow-up: verify the 50 MB cloud limit at deployment and select the local Bot API mode for Premium 4K.

### D-19 — Sponsor placement policy

- Chosen: free users only; exactly one placement per successful download, sent after delivery; no PII or preference tracking; content moderation deferred.
- Reason: owner decision. Keeps placements non-personalized and separate from delivery reliability.
- Implementation/configuration impact: placement must be emitted only after confirmed Telegram delivery; no placement on failure paths.
- Follow-up: allowed-content and moderation policy in the next phase; campaign billing and targeting remain open.

## Recommended defaults to evaluate

These are discussion starters, not approved decisions:

- Premium quota: 20/day (now approved).
- Reward credit: one credit per verified completion, expiring at the end of the quota day.
- Reward cap: 10 rewarded downloads per user per day.
- Cache: 50 GiB initial storage cap (approved); retention is already capped at 24 hours.
- Deployment: one region close to the initial user base, selected after latency, cost and policy review.

## Decision record format

For each resolved item, record:
- Decision ID and date.
- Chosen value.
- Alternatives considered.
- Reason.
- User-facing impact.
- Implementation/configuration impact.
- Tests and documentation updated.
