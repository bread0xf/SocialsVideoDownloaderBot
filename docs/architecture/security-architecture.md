# Security Architecture

**Implementation status:** URL validation, the ingestion DNS guard, final extracted-URL allowlisting, isolated subprocess environments, argument-array process execution, bounded timeouts and output caps, non-root container execution, secret-free logging and quota/entitlement integrity are implemented and unit- or integration-tested. Controlled egress/network policy for full DNS-rebinding protection, automated live Telegram delivery tests, rate limiting and the billing/reward controls are **not implemented**. See `docs/implementation-status.md`.

**Hosted development note:** the Railway dev worker runs with `RAILWAY_RUN_UID=0` because the persistent volume is mounted root-owned. That is a development-only concession; production must use an entrypoint chown/drop or object storage instead.

## 1. Threat model

Assets:
- Telegram bot token and webhook secret.
- Payment and rewarded-ad provider secrets.
- User identity and chat identifiers.
- Quota, subscription and reward ledgers.
- Download worker, host filesystem and network.
- Cached media and Telegram file references.

Threats:
- SSRF through user-supplied URLs or redirects.
- Private/restricted content access attempts.
- Malicious media, parser/extractor vulnerabilities and resource exhaustion.
- Queue/job replay, duplicate callbacks and quota race conditions.
- Payment/reward spoofing.
- Secret leakage through logs, errors or process arguments.
- Cache entitlement bypass.
- Unauthorized internal API access.

## 2. URL validation and SSRF

- Accept only exact supported hostnames and expected path patterns.
- Reject URL userinfo, unexpected ports, malformed encodings and ambiguous host representations.
- Resolve DNS and reject loopback, private, link-local, multicast, reserved and internal ranges.
- Revalidate every redirect target and DNS resolution.
- Protect against DNS rebinding by enforcing network egress restrictions at the worker/container level.
- Do not allow extractor plugins to fetch arbitrary metadata URLs without the same network controls.
- Prefer an outbound proxy or network policy that blocks internal address space.
- Do not rely on hostname validation alone.

## 3. Extraction isolation

- Run extraction in a restricted worker environment.
- No host Docker socket, privileged container, or unnecessary capabilities.
- Use non-root user, read-only root filesystem where practical, bounded writable workspace and resource quotas.
- Apply CPU, memory, disk, process, network and wall-clock limits.
- Keep yt-dlp and FFmpeg updated; pin versions and review security advisories.
- Never pass user-controlled strings into a shell command. Use argument arrays and safe subprocess APIs.
- Do not supply cookies, browser profiles or social credentials.

## 4. Media processing

- Treat downloaded media and metadata as untrusted.
- Generate server-side filenames; never trust remote filenames as filesystem paths.
- Use per-job isolated directories.
- Validate output size, duration, codec and container.
- Prevent path traversal and symlink attacks.
- Clean temporary data on success, failure, timeout and cancellation.
- Do not expose filesystem paths in user-facing errors.

## 5. Authentication, payments and rewards

- Treat Telegram user ID as identity for bot interactions; authorize all operations server-side.
- Validate webhook secret token when using Telegram webhooks.
- Verify Telegram Stars payment updates against expected invoice, amount and currency.
- Use idempotency keys and unique provider references.
- Authenticate reward-provider callbacks, validate timestamps/nonces and reject replay.
- Never credit rewards from client-side claims.
- Restrict admin functions and provider secrets to least-privilege roles.
- Adsun reward callbacks use a static shared secret in the query string because the provider contract offers no signature header. Keep Uvicorn access logging disabled, never log the URL or query string, and return `Cache-Control: no-store` on every callback response.
- Neutral-path aliases `GET /api/v1/hooks/r1/cb` and `GET /api/v1/hooks/r1/probe` mount the same handler objects as `/api/v1/rewards/adsun/callback` and `/api/v1/rewards/adsun/capture`; they exist because Adsun's panel switches a block to "Use Adsun Rewards URL" when the path contains `rewards/adsun`. They are hidden from OpenAPI and inherit the secret check, capture gating, test-callback handling, no-store headers and log-redaction rules by construction.
- The reward idempotency key is derived from provider, Telegram user id, normalised block id and the second-resolution event timestamp. Retries collapse to one grant. A callback can only redeem a pending `reward_sessions` row created when the bot served an ad; without one it returns `no_session`, so changing the timestamp does not mint a credit. A leaked secret can still redeem another user's pending session, bounded by one session per user/provider/block and the daily cap. Rotate the secret after suspected exposure; per-secret rate limiting and alerting remain open.
- The pending reward session is the ad cooldown. The bot must create or reuse it before fetching an ad, and must not fetch a second ad while one is pending. Expired sessions are never redeemable.
- Before opening a session or calling the ad provider, the bot runs an advisory eligibility pre-check (blocked, Premium per `REWARD_PREMIUM_ELIGIBLE`, and the Lagos-day grant cap). Ineligible users get no session row and no ad. The callback repeats every check under the per-user advisory lock and stays authoritative, so a pre-check race can only over-serve an ad, never mint a credit.
- Adsun test probes (`test=1` or `test=true`) are only accepted after the same constant-time secret check. They return `200` with `{"status":"test"}` and write nothing: no claim row, no session redemption, no credit. Logs record parameter names only. The temporary capture route treats them the same but keeps its non-secret value logging.
- A temporary staging-only `GET /api/v1/rewards/adsun/capture` route exists behind `ADSUN_CAPTURE_ENABLED=false` and refuses to run when `APP_ENV=production`. It verifies the callback secret, logs parameter names and non-secret values plus receive time (never the secret or full URL), and fails the first call per `(userid, block)` to expose retry behaviour. Remove it, its flag and its tests before production.
- Log callback database failures by error class only. Never include the exception message or traceback, which may capture request data or the callback secret.

## 6. Quota and entitlement integrity

- PostgreSQL is authoritative.
- Reserve quota transactionally and safely under concurrency.
- Commit only after delivery confirmation; release or reconcile terminal failures.
- Re-evaluate entitlements on cache hits.
- Do not trust user-supplied plan codes or callback data as proof of entitlement.
- Record auditable ledger events.

## 7. Secrets and logging

- Store secrets in environment/secret manager, not source control.
- Rotate bot and provider tokens after suspected exposure.
- Redact tokens, authorization headers, sensitive URL parameters and payment payload secrets.
- Use structured logs with request/update/job correlation IDs.
- Avoid logging media contents or unnecessary personal data.
- Restrict access to logs and define retention.

## 8. Abuse and availability

- Rate-limit per user and globally.
- Bound concurrent jobs, media size, duration and processing time.
- Add circuit breakers/feature flags for unstable platform adapters.
- Apply queue backpressure and worker concurrency limits.
- Detect repeated malformed URLs and abusive usage.
- Provide safe failure modes when a provider or platform is unavailable.

## 9. Security testing

Required tests include:
- SSRF payloads, IP literal tricks, DNS rebinding assumptions and redirect chains.
- Unsupported host and deceptive hostname rejection.
- Private/restricted content refusal.
- Path traversal and hostile filenames.
- Oversized/long-duration media and resource exhaustion.
- Duplicate payment/reward callbacks.
- Quota race conditions and duplicate Telegram updates.
- Cache hit with expired/downgraded entitlement.
- Secret redaction in logs and exception paths.

## 10. Operational response

Maintain procedures for:
- Bot token compromise.
- Payment/reward provider secret compromise.
- Malicious media or extractor exploit.
- Queue backlog and worker resource exhaustion.
- Platform adapter breakage.
- Data exposure and user deletion requests.
