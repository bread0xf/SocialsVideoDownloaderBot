# 04 — Download Pipeline Specification

## 1. State machine

```text
RECEIVED
  -> VALIDATING
  -> AUTHORIZING
  -> QUEUED
  -> EXTRACTING
  -> SELECTING_FORMAT
  -> PROCESSING
  -> DELIVERING
  -> COMPLETED

Terminal alternatives: REJECTED, FAILED, CANCELLED
```

Persist state transitions. Reject invalid transitions. Record stage timestamps and safe error codes. Retries are bounded and only allowed for transient categories.

## 2. Processing sequence

1. Receive Telegram update and deduplicate it.
2. Parse URL and create a job record.
3. Validate scheme, host, DNS, redirects and supported platform/content type. Revalidate the extractor's final URL against the platform allowlist before downloading.
4. Resolve user's current entitlement.
5. Atomically reserve included allowance or reward credit.
6. Persist job and outbox event in one DB transaction.
7. Outbox dispatcher publishes job ID to ARQ.
8. Worker claims job with lease/heartbeat and increments attempt count.
9. Extract metadata and formats through platform adapter.
10. Select highest eligible output under entitlement and configured limits.
11. Download to isolated workspace.
12. Merge/remux using FFmpeg only when required.
13. Verify streams, duration, resolution, size and container with FFprobe.
14. Deliver through Telegram.
15. Only after Telegram confirms success, commit usage reservation and write ledger entry.
16. Store cache metadata and reusable Telegram `file_id` where safe.
17. Delete temporary workspace; cache output follows 24-hour retention.

## 3. Job reliability

- Queue message contains a job ID, not the full source URL or user secrets.
- PostgreSQL is authoritative for job state.
- Outbox dispatcher retries unpublished events with backoff.
- Worker claims are protected by DB state/lease to prevent duplicate processing.
- A duplicate task should inspect durable state and exit safely if already terminal or actively leased.
- Retry only transient network/extractor/Telegram failures. Do not retry invalid URLs, policy blocks, quota exhaustion or unsupported content.
- Use bounded attempts, exponential backoff with jitter, and a maximum job age.
- On worker restart, stale leases are detected and eligible jobs requeued.
- Telegram delivery ambiguity must be handled carefully: persist delivery attempt metadata and use Telegram `file_id`/message identifiers when available to avoid duplicate sends where possible. Never commit quota before confirmed successful delivery.

## 4. Format selection

- Free max resolution: 480p.
- Premium max resolution: 2160p, subject to configured limits.
- Resolution is the shorter video dimension (`min(width, height)`), so portrait videos are classified correctly.
- Prefer highest eligible resolution.
- Prefer combined A/V when equivalent; otherwise select compatible streams and merge.
- Reject formats exceeding configured max bytes, duration, codec/container or processing budgets.
- If the platform exposes no rendition at or below the plan ceiling, select the smallest available rendition and downscale it to the ceiling.
- Silent videos are valid; deliver video-only when the source has no audio stream.
- Do not upscale.
- Do not claim a resolution unsupported by source.
- FFprobe validates actual output; metadata alone is insufficient. Output validation also uses the shorter dimension.

## 5. Resource controls

Configurable limits must include:
- Maximum source duration.
- Maximum output bytes.
- Extraction timeout.
- Processing timeout.
- Per-job disk budget.
- Worker concurrency.
- Per-user active job limit.
- Queue age / retry count.
- CPU and memory limits at container/process level.

Initial values are deployment/product configuration, not invented business promises. Set safe conservative development defaults and require explicit production configuration.

## 6. Workspace and cache

- Use a generated UUID workspace under a configured root.
- Never use user-provided filenames/paths directly.
- Restrict permissions and ensure path containment.
- Delete workspace on all terminal paths, including cancellation and exceptions.
- Cache only verified outputs; 24-hour maximum retention.
- Cache identity includes canonical source identity, output profile, processing version and relevant source metadata.
- Entitlement must be rechecked before cached delivery.
- Cache hit must still create a job and follow normal quota accounting.
