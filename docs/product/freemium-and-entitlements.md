# Freemium, Billing and Entitlements

**Status:** Core policy direction agreed; numeric and provider details remain partly open.

## 1. Plans

| Capability | Free | Premium |
|---|---|---|
| Daily allowance | 5 successful downloads | Higher configured quota — OPEN |
| Rewarded extra download | Proposed: +1 per verified ad | OPEN |
| Output quality | Below 720p; 480p proposed ceiling | Best supported, up to 4K |
| Processing priority | Standard | Proposed priority queue |
| Bot-owned sponsor placements | May be shown | Excluded |
| Billing | No subscription | Monthly subscription |

Telegram's own advertising product is separate from sponsor placements controlled by the bot operator.

## 2. Quota semantics

- Count successful Telegram deliveries, not accepted URLs, queued jobs or extraction attempts.
- Use a clearly defined daily reset policy and timezone. **OPEN:** choose UTC or a documented product timezone.
- Enforce quota atomically in PostgreSQL.
- Create a reservation when authorizing a job; commit it only after confirmed delivery.
- Release or reconcile reservations after terminal failure/cancellation.
- Define behavior for ambiguous Telegram delivery outcomes; reconciliation must prevent both free delivery abuse and duplicate quota charges.
- Use idempotency keys for Telegram update/job identity.
- Do not allow concurrent requests to overspend the same quota.

## 3. Rewarded credits

Proposed behavior: a verified completed ad event grants one additional download credit.

Still unresolved:
- Provider and integration type.
- Whether the provider supports server-side reward verification.
- Daily reward cap.
- Credit expiry.
- Whether Premium users can earn credits.
- Geographic availability and monetization suitability.
- Provider callback authentication and replay defense.

Never grant a credit from a client-side “ad watched” message alone. If provider verification is unavailable, do not ship rewarded credits.

## 4. Premium subscription

- Monthly subscription.
- Telegram Stars is the initial proposed payment rail.
- Price in Stars: OPEN.
- Premium quota: OPEN.
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
