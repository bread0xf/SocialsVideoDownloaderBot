# Unresolved Decisions and Approval Register

Do not silently decide these on behalf of the project owner.

> `backend_specs/` is the implementation baseline and supersedes this file on conflict. Decisions recorded as resolved below are locked there and must not be reopened without explicit owner instruction.

| ID | Decision | Current direction | Needed before |
|---|---|---|---|
| D-02 | Premium monthly price | Telegram Stars proposed; amount open | Billing implementation |
| D-03 | Premium daily quota | Higher than Free; exact number open | Billing/entitlement implementation |
| D-04 | Rewarded-ad provider | Not selected | Reward feature |
| D-05 | Reward daily cap | Open | Reward feature |
| D-06 | Reward credit expiry | Open | Reward feature |
| D-07 | Premium reward eligibility | Open | Reward feature |
| D-09 | Premium priority semantics | Higher processing priority proposed | Queue implementation |
| D-10 | Telegram upload limits | Must verify current API/deployment constraints | Delivery implementation |
| D-11 | Cache storage cap | Configurable; value open (24h retention locked) | Deployment |
| D-12 | Hosting provider/region | Open | Deployment |
| D-13 | Webhook vs long polling | Open; choose based on deployment | Bot deployment |
| D-14 | Subscription renewal/cancellation/refund behavior | Define Telegram Stars lifecycle | Billing release |
| D-15 | Legal/policy basis and takedown process | Review required | Public launch |

## Resolved decisions

| ID | Decision | Chosen value | Recorded |
|---|---|---|---|
| D-01 | Free maximum resolution | 480p | 2026-11-06 (`backend_specs/`) |
| D-08 | Daily quota reset timezone | Local midnight `Africa/Lagos`; persist UTC | 2026-11-06 (`backend_specs/`) |

## Recommended defaults to evaluate

These are discussion starters, not approved decisions:
- Premium quota: a published fair-use limit rather than “unlimited”.
- Reward credit: one credit per verified completion, expiring at the end of the quota day.
- Cache: strict storage cap; retention is already capped at 24 hours.
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
