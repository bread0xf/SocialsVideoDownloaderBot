# 05 — Entitlements and Monetization

## 1. Free plan (locked)

- Five successful downloads per `Africa/Lagos` calendar day.
- Maximum resolution 480p.
- Standard processing priority.
- Rewarded credits may be earned after included allowance is exhausted, once a provider is selected and verified.
- May receive bot-managed sponsor placements.

## 2. Premium plan (partially locked)

- Monthly subscription.
- Initial payment method: Telegram Stars.
- Maximum resolution up to 4K where source and delivery allow.
- Priority processing.
- No bot-managed sponsor placements.
- Access remains valid through `paid_through`; entitlement expires after that instant.

**Unresolved:** Premium daily download allowance and subscription price. Do not invent either. Keep values configurable and do not expose purchase UI until approved.

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

- Rewarded completion must be verified server-side.
- Mini App/client cannot grant credits.
- Provider callback authentication and replay protection are mandatory.
- One provider transaction ID can grant once only.
- Credits are recorded in append-only reward ledger.
- Provider integration must be abstracted.

**Unresolved:** provider, reward quantity, daily cap and credit expiry. Do not grant credits through a development shortcut in production. Feature remains disabled until selected.

Telegram sponsored messages are not a rewarded-ad completion mechanism.

## 6. Telegram Stars subscriptions

Implement only after product pricing and allowance are approved. Payment module must support:
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

Own sponsor placements are distinct from Telegram's own ad system. Free users may receive configured placements; Premium users do not. Sponsor content should be escaped/sanitized and have active date/status checks. Campaign billing and analytics are outside the initial downloader slice.
