# Freemium, Billing and Entitlements

**Status:** Core policy direction agreed. Free allowance, free quality ceiling, quota timezone and media retention are locked by `backend_specs/`. Premium pricing and allowance were approved on 2026-11-06. Reward provider mechanics remain partially open.

> `backend_specs/` is the implementation baseline. Where this document conflicts with it, the specification pack wins.

## 1. Plans

| Capability | Free | Premium |
|---|---|---|
| Daily allowance | 5 successful downloads per `Africa/Lagos` calendar day | 20 successful downloads per `Africa/Lagos` calendar day |
| Rewarded extra download | One additional download per verified ad | Proposed: not eligible, because Premium excludes sponsor placements |
| Output quality | Up to 480p (locked ceiling) | Best supported, up to 4K |
| Processing priority | Standard | Proposed priority queue |
| Bot-owned sponsor placements | Exactly one per successful download, sent after delivery | Excluded |
| Billing | No subscription | 150 Telegram Stars per 30-day month, purchased through bot commands |

Telegram's own advertising product is separate from sponsor placements controlled by the bot operator.

Sponsor policy (approved 2026-11-06): free users receive exactly one placement per successful download, sent after the media file is delivered. No placement is shown on failed or failed-to-deliver jobs. Content moderation is deferred to the next phase. No PII is collected and no user-preference tracking is performed; placements are not personalized. Any free user can purchase Premium through bot commands, with checkout following Telegram's Stars process.

## 2. Quota semantics

- Count successful Telegram deliveries, not accepted URLs, queued jobs or extraction attempts.
- The daily quota period resets at local midnight in `Africa/Lagos` (locked). Persist timestamps in UTC and convert only for period calculation/presentation; compute the boundary independently and handle DST safely even though Lagos currently has no DST.
- Enforce quota atomically in PostgreSQL.
- Create a reservation when authorizing a job; commit it only after confirmed delivery.
- Release or reconcile reservations after terminal failure/cancellation.
- Define behavior for ambiguous Telegram delivery outcomes; reconciliation must prevent both free delivery abuse and duplicate quota charges.
- Use idempotency keys for Telegram update/job identity.
- Do not allow concurrent requests to overspend the same quota.

## 3. Rewarded credits

Approved behavior (2026-11-06): a verified ad event grants one additional download credit, delivered as a bot-managed chat/sponsor message. Users may earn repeatedly, subject to the daily cap.

Still unresolved:
- Exact delivery mechanism: bot-managed message with a single-use server token vs. third-party rewarded-ad network.
- Daily reward cap (proposed: 10 rewarded downloads per user per Lagos day).
- Credit expiry (proposed: end of the Lagos quota day earned).
- Whether Premium users can earn credits (proposed: no, because Premium excludes sponsor placements).
- Geographic availability and monetization suitability.
- Callback/postback authentication and replay defense.

Telegram has no official rewarded-ad API for bots, and official Sponsored Messages do not expose a per-user completion event. Never grant a credit from a client-side “ad watched” message alone. A bot-managed placement must use a single-use, server-issued token and a minimum dwell time; a third-party provider must use authenticated server-to-server postback. If neither can be enforced, do not ship rewarded credits.

## 4. Premium subscription

- Monthly subscription; Telegram Stars subscription periods are fixed at 30 days.
- Telegram Stars is the payment rail.
- Access remains valid through the recorded `paid_through` instant; entitlement expires after it.
- Price: 150 Stars per 30-day month (approved 2026-11-06).
- Premium quota: 20 included downloads per `Africa/Lagos` day (approved 2026-11-06).
- Grace period, cancellation, refund and renewal behavior: define before launch.
- Store Telegram payment identifiers and provider payload references with appropriate access controls.
- Verify successful payment through trusted Telegram payment updates; do not trust client claims.
- Process each payment update idempotently.
- Maintain a durable entitlement history and reconcile subscription state.

## 5. Entitlement model

Represent effective entitlements as server-derived policy, not UI state:

```text
PlanEntitlement
  plan_id
  daily_download_limit
  max_height
  processing_priority
  sponsor_free
  reward_eligible
  effective_from
  effective_until
```

Use plan configuration and subscription state to derive effective entitlement. Preserve historical billing/ledger records when a plan changes.

## 6. Cache interaction

Processed media cache has a hard maximum retention of 24 hours (locked).

A cache hit does not bypass authorization:
1. Identify cache artifact.
2. Re-evaluate the requesting user's current entitlement.
3. Verify cached output profile satisfies that entitlement.
4. Deliver through Telegram.
5. Record successful delivery and quota consumption under the same rules as a fresh job.

## 7. Abuse controls

- Per-user and per-chat rate limits.
- Limits on concurrent jobs and maximum media size/duration.
- Detect repeated failed requests and suspicious automation.
- Prevent reward callback replay and duplicate credit issuance.
- Apply fair-use controls without silently changing published plan terms.
