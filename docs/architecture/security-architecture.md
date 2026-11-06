# Security Architecture

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
