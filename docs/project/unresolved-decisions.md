# Unresolved Decisions and Approval Register

Do not silently decide these on behalf of the project owner.

| ID | Decision | Current direction | Needed before |
|---|---|---|---|
| D-01 | Free maximum resolution | Below 720p; 480p proposed | Public launch |
| D-02 | Premium monthly price | Telegram Stars proposed; amount open | Billing implementation |
| D-03 | Premium daily quota | Higher than Free; exact number open | Billing/entitlement implementation |
| D-04 | Rewarded-ad provider | Not selected | Reward feature |
| D-05 | Reward daily cap | Open | Reward feature |
| D-06 | Reward credit expiry | Open | Reward feature |
| D-07 | Premium reward eligibility | Open | Reward feature |
| D-08 | Daily quota reset timezone | UTC or product timezone; open | Quota implementation |
| D-09 | Premium priority semantics | Higher processing priority proposed | Queue implementation |
| D-10 | Telegram upload limits | Must verify current API/deployment constraints | Delivery implementation |
| D-11 | Cache TTL and storage cap | Configurable; values open | Deployment |
| D-12 | Hosting provider/region | Open | Deployment |
| D-13 | Webhook vs long polling | Open; choose based on deployment | Bot deployment |
| D-14 | Subscription renewal/cancellation/refund behavior | Define Telegram Stars lifecycle | Billing release |
| D-15 | Legal/policy basis and takedown process | Review required | Public launch |

## Recommended defaults to evaluate

These are discussion starters, not approved decisions:
- Daily reset: UTC for predictable accounting.
- Free cap: 480p.
- Premium quota: a published fair-use limit rather than “unlimited”.
- Reward credit: one credit per verified completion, expiring at the end of the quota day.
- Cache: short configurable TTL with strict storage cap.
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
