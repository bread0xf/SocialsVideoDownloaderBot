# 06 — Security and Privacy Requirements

## 1. Threat model priorities

- SSRF through submitted URLs, redirects or extractor behavior.
- DNS rebinding and internal-network access.
- Malicious media/container payloads and parser vulnerabilities.
- Command injection or unsafe subprocess arguments.
- Path traversal and workspace escape.
- Resource exhaustion (CPU, RAM, disk, network, queue).
- Duplicate Telegram updates, jobs, payment events or reward callbacks.
- Quota race conditions and double spending.
- Secret leakage through logs, errors, crash reports or environment files.
- Unauthorized access to job status or cached media.

## 2. URL and network safety

- Only HTTP/HTTPS.
- Exact allowlist of platform hosts and tested URL patterns.
- Reject IP-literal, localhost, private, loopback, link-local, multicast and reserved destinations.
- Revalidate every redirect and resolved destination.
- Defend against DNS rebinding; validate at connection time or route extraction through controlled egress.
- Do not fetch arbitrary URLs or user-provided manifests.
- Keep extractor network access restricted to required platform/CDN hosts where practical.

## 3. Extractor and process isolation

- Run workers with least privilege and no unnecessary capabilities.
- Use argument arrays, never shell interpolation.
- Do not expose arbitrary yt-dlp flags.
- Set timeouts, CPU/memory/disk limits and concurrency caps.
- Isolated per-job directories with restrictive permissions.
- Validate output with FFprobe; treat media as untrusted input.
- Keep FFmpeg/yt-dlp updated and rebuild images promptly for security fixes.
- No cookies or user social account credentials.

## 4. API, Telegram and callbacks

- Keep bot token and provider secrets in injected environment/secrets manager.
- Authenticate internal service calls.
- Validate Telegram Mini App `initData` server-side when Mini App exists.
- Verify provider callback signatures and replay windows.
- Unique provider transaction/event IDs.
- Idempotent handlers and durable audit records.
- Apply per-user and global rate limits.

## 5. Data minimization

- Store only Telegram identity fields required for bot operation.
- Do not store social account credentials, cookies or private media.
- Avoid full URLs in logs; redact query strings/tokens.
- Keep temporary workspaces short-lived.
- Processed cache retention maximum 24 hours.
- Define backup retention and deletion policy before production.
- Restrict access to payment and operational data.

## 6. User-facing errors

Return stable safe categories. Do not reveal stack traces, internal hostnames, file paths, IPs, raw extractor output, secrets or payment payloads.
