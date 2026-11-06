# 05 — Entitlements and Monetization

## 1. Free plan (locked)

- Five successful downloads per `Africa/Lagos` calendar day.
- Maximum resolution 480p.
- Standard processing priority.
- Rewarded credits may be earned after included allowance is exhausted, once a provider is selected and verified.
- May receive bot-managed sponsor placements.

## 2. Premium plan

- Monthly subscription, 30 days (Telegram Stars fixed subscription period).
- Price: **150 Telegram Stars** (approved 2026-11-06).
- Daily included allowance: **20 successful downloads per `Africa/Lagos` day** (approved 2026-11-06).
- Initial payment method: Telegram Stars.
- Maximum resolution up to 4K where source and delivery allow.
- Priority processing.
- No bot-managed sponsor placements.
- Access remains valid through `paid_through`; entitlement expires after that instant.

Keep price and allowance configurable. Do not expose purchase UI until the billing module is implemented and Telegram's current terms are re-verified.

## 3. Entitlement resolution

Resolve an immutable entitlement snapshot for each accepted job:
- plan code;
- max resolution;
- daily included allowance;
- processing priority;
- sponsor eligibility;
- entitlement evaluation timestamp;
- subscription ID and paid-through instant where relevant.

The job's snapshot aids auditability, but current entitlement must be rechecked before delivery from cache if policy requires it. Do not allow a stale cached Telegram `file_id` to bypass entitlement.

## 4. Quota policy

- Quota period is midnight-to-midnight in `Africa/Lagos`.
- Successful downloads count only after Telegram delivery succeeds.
- Reserve capacity atomically before queueing.
- Commit after delivery.
- Release after definitive failure.
- Included allowance is consumed before rewarded credits.
- Usage ledger is append-only.
- Redis counters may be used as non-authoritative optimization only; reconcile against PostgreSQL.

## 5. Rewarded ads

- Delivery direction (approved 2026-11-06): bot-managed chat/sponsor messages; a user watches an ad and receives **one additional download**.
- Rewarded completion must be verified server-side.
- Mini App/client cannot grant credits.
- Callback authentication and replay protection are mandatory.
- One ad token or provider transaction ID can grant once only.
- Credits are recorded in an append-only reward ledger and consumed after the included allowance.
- Provider integration must be abstracted.

**Partially unresolved:** daily cap and credit expiry. Proposed daily cap is 10 rewarded downloads per user per Lagos day; proposed expiry is the end of the Lagos quota day the credit was earned. Both require owner approval.

Telegram has no official rewarded-ad API for bots; official Sponsored Messages do not provide a per-user completion event. A rewarded flow must be a bot-managed placement with a single-use server token and a minimum dwell time, or a third-party provider with authenticated server-to-server postback. Do not grant credits through a development shortcut in production. Feature remains disabled until the mechanism and cap are approved.

## 6. Telegram Stars subscriptions

Pricing and allowance are approved (150 Stars / 30 days; 20 downloads/day). Any free user can start a purchase through bot commands; checkout and billing follow Telegram's Stars process, with no separate web checkout. Payment module must support:
- invoice creation;
- verified successful payment events;
- immutable payment records;
- subscription activation and `paid_through` extension;
- renewal;
- cancellation;
- expiry;
- refund/reversal handling consistent with Telegram requirements.

Use provider transaction IDs and idempotency keys. Never activate subscription based solely on a client callback or invoice creation.

## 7. Sponsor placements

Own sponsor placements are distinct from Telegram's own ad system. Approved policy (2026-11-06):

- Free users only; Premium users never receive placements.
- Exactly one placement per successful free download, sent after the media is delivered.
- No placement on failed, rejected or cancelled jobs.
- Content moderation and allowed-content review are deferred to the next phase, after the sponsor system works end to end.
- No PII collection and no user-preference tracking; placements are not personalized.
- Sponsor content must be escaped/sanitized and have active date/status checks.
- Campaign billing and detailed analytics remain outside the initial downloader slice.
