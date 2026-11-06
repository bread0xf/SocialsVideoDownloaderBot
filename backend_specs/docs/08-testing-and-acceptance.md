# 08 — Testing and Acceptance Criteria

## 1. Unit tests

- URL parser, normalization and platform host recognition.
- Entitlement resolution and `paid_through` boundary.
- Quality selection and fallback.
- Lagos local-day quota boundary conversion.
- Quota reservation/commit/release state transitions.
- Reward-credit balance and included-first ordering.
- Job state transition validation.
- Cache-key construction and expiry policy.
- Stable error mapping.

## 2. Integration tests

Use PostgreSQL and Redis test instances/containers:
- Alembic migrations from empty DB.
- User upsert/idempotency from Telegram identity.
- Concurrent quota reservation does not overspend.
- Commit ledger entry exactly once.
- Failure releases reservation without consuming successful allowance.
- Reward grant callback replay cannot duplicate credits.
- Payment event replay cannot duplicate payment or subscription extension.
- Outbox event is published after commit and retried after dispatcher failure.
- Stale worker lease recovery.
- Cache cleanup removes expired files and reconciles DB state.

## 3. Adapter and media tests

- Controlled public test URLs for each advertised content type.
- Unsupported/private/restricted URL rejection.
- Extractor timeout and unavailable source handling.
- Combined format and separate A/V merge paths.
- FFprobe output verification.
- File-size/duration/resource limit enforcement.
- Telegram delivery mocked in CI; dedicated test bot for controlled E2E.

Do not make CI depend on unstable third-party URLs for every run. Keep a small scheduled compatibility suite separate from deterministic unit/integration tests.

## 4. Security tests

- SSRF attempts against localhost/private/link-local/IPv6 local ranges.
- Redirect to prohibited destination.
- DNS rebinding defense at connection boundary.
- URL credentials, malformed host, unusual port, non-HTTP scheme.
- Path traversal and malicious filename handling.
- Shell metacharacter input cannot execute commands.
- Oversized/long-running media hits resource limits.
- Logs do not contain tokens, cookies or sensitive query values.
- User A cannot access User B's job/cache metadata.
- Duplicate Telegram update is idempotent.

## 5. Acceptance criteria

The first vertical slice is accepted only when:
1. `/start` and `/help` work.
2. Valid supported public URLs create persistent jobs.
3. Unsupported or unsafe URLs are rejected before extraction.
4. Worker processes jobs asynchronously; bot update handling remains responsive.
5. Free users are limited to 480p and five successful downloads per Lagos calendar day.
6. Quota is reserved atomically and committed only after Telegram delivery succeeds.
7. Failed jobs release reservations and do not count as successful downloads.
8. Concurrent requests cannot overspend quota.
9. Temporary workspaces are removed on all terminal paths.
10. Processed media expires no later than 24 hours.
11. Duplicate tasks/updates do not double-charge or duplicate durable ledger entries.
12. Service restart does not silently lose committed jobs.
13. Tests and Ruff pass; migrations apply cleanly.
14. `.env.example` and run instructions are complete.

Monetization acceptance is separate and gated by the open decisions in `09-open-decisions.md`.
