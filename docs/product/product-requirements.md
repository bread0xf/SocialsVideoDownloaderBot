# Product Requirements — SocialsVideoDownloaderBot

**Status:** MVP specification. Implemented scope and gaps are tracked in `docs/implementation-status.md`; commercial and operational values still open are in `docs/project/unresolved-decisions.md`.

## 1. Product overview

SocialsVideoDownloaderBot accepts a supported public social-media video link, validates it, obtains an accessible media representation through a platform adapter, applies the user's entitlement-based output profile, and sends the resulting video to the user in Telegram.

## 2. Target experience

1. User opens the bot and starts a conversation.
2. Bot explains supported platforms, public-content-only policy and daily allowance.
3. User sends a supported video URL.
4. Bot validates the URL and checks user eligibility/quota.
5. Bot creates an asynchronous job and reports progress using concise status messages.
6. Worker extracts available formats, selects an allowed output, downloads/processes it and delivers it through Telegram.
7. Successful delivery is recorded and the user's quota is committed.
8. If the free allowance is exhausted, the bot explains the available options: wait for reset, complete an eligible rewarded-ad flow, or subscribe to Premium.

## 3. MVP scope

### Included
- Telegram bot interface.
- TikTok, Instagram, YouTube and Facebook public video URLs.
- URL validation and platform identification.
- Asynchronous download jobs.
- Automatic format selection based on plan.
- Telegram delivery.
- Free daily quota and monthly Premium entitlement.
- Rewarded-download credit flow, once a provider is selected and integrated.
- Payment/entitlement lifecycle using Telegram Stars as the initial proposed payment direction.
- Media caching with entitlement revalidation.
- Admin-operational visibility through structured logs and health endpoints.
- User-facing errors for unsupported, inaccessible, restricted, expired and failed content.

### Excluded
- Private/restricted content or content requiring account authentication.
- Login, cookie import, browser-profile extraction or credential collection.
- DRM circumvention or bypassing access controls.
- Arbitrary direct-file URLs.
- Playlists, channels, live streams, batch downloads or scheduled downloads.
- User-selectable resolution in the MVP; selection is automatic.
- Delivery outside Telegram.
- Public tracking API.
- Full Telegram Mini App interface (architecture should not prevent a later Mini App).

## 4. User stories and acceptance criteria

### First use
- As a user, I can start the bot and see a concise explanation of supported platforms and limits.
- Acceptance: `/start` is idempotent; user record is created or updated without duplicate accounts.

### Submit a link
- As a user, I can submit a supported public video URL.
- Acceptance: only approved host/path patterns are accepted; malformed and unsupported links are rejected before queueing.

### Download
- As a user, I receive the video in Telegram after processing.
- Acceptance: work is asynchronous; progress and terminal status are communicated; temporary files are cleaned up.

### Quota
- As a Free user, I can complete five successful downloads per daily quota window.
- Acceptance: only successful Telegram deliveries consume quota; duplicate updates do not create duplicate charges.

### Rewarded download
- As an eligible user, I can complete a rewarded-ad flow and receive one additional download credit.
- Acceptance: credit is granted only from a verified, authenticated, fresh and idempotently processed provider event. This feature remains blocked until provider and policy decisions are approved.

### Premium
- As a Premium subscriber, I receive the configured Premium quota and quality entitlement.
- Acceptance: entitlement is verified server-side at job authorization and rechecked before cache delivery.

## 5. Functional requirements

- FR-01: Identify the platform from a normalized URL.
- FR-02: Validate URL scheme, host, path and redirect behavior.
- FR-03: Resolve Telegram user identity and maintain user records.
- FR-04: Enforce per-user request rate limits and quota.
- FR-05: Persist jobs before queue publication using an outbox pattern.
- FR-06: Execute extraction and media processing asynchronously.
- FR-07: Select formats automatically under the user's current entitlement.
- FR-08: Deliver media to the originating Telegram chat.
- FR-09: Record delivery outcome and commit/release quota reservation accordingly.
- FR-10: Cache eligible media and Telegram file identifiers.
- FR-11: Process subscription and reward events idempotently.
- FR-12: Expose health/readiness checks without disclosing sensitive internals.
- FR-13: Provide safe, actionable error messages.

## 6. Non-functional requirements

- Security: SSRF defenses, strict input validation, least privilege, secret redaction.
- Reliability: durable jobs, retries with bounds, idempotent processing and reconciliation.
- Performance: fast acknowledgement; long work must not block Telegram update handling.
- Scalability: independent worker concurrency controls while retaining modular-monolith boundaries.
- Maintainability: typed interfaces, migrations, tests, structured logs and documented decisions.
- Privacy: collect only data required for operation, billing, abuse prevention and support.
- Observability: correlate update, job and delivery IDs without exposing sensitive payloads.

## 7. Product metrics

Track at minimum:
- Submitted links, accepted links and rejection reasons.
- Jobs queued, completed, failed and timed out.
- Median and p95 processing duration.
- Telegram delivery success/failure.
- Cache hit rate.
- Free quota utilization.
- Premium conversion, renewal and cancellation.
- Reward events received, verified, rejected and credited.
- Platform-specific extraction failure rate.

Avoid collecting unnecessary content or raw location data.

## 8. Launch gates

- Confirm lawful and platform-policy basis for each supported platform.
- Confirm Telegram Bot API file delivery limits and deployment implications.
- Finalize Stars price, Premium quota and renewal/cancellation behavior.
- Select and contract a rewarded-ad provider, or disable rewarded ads for launch.
- Confirm the free output ceiling.
- Complete security and abuse testing.
