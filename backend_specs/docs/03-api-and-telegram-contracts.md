# 03 — API and Telegram Contracts

## 1. General

FastAPI is used for health checks and later Mini App/provider callbacks. The Telegram bot should call application services directly rather than loop through its own HTTP API. Internal routes must not be exposed publicly without authentication.

All JSON APIs use Pydantic request/response models, stable error codes, request correlation IDs and UTC ISO-8601 timestamps.

## 2. Proposed HTTP surface

| Method | Path | Purpose | Phase |
|---|---|---|---|
| GET | `/health/live` | Process liveness | 0 |
| GET | `/health/ready` | DB/Redis readiness | 0 |
| GET | `/api/v1/platforms` | Active platform capabilities | 1 |
| GET | `/api/v1/users/me` | Account/entitlement summary for Mini App | Later |
| POST | `/api/v1/downloads` | Create download request if external client needed | Optional |
| GET | `/api/v1/downloads/{id}` | Job status for authenticated owner | Optional |
| POST | `/api/v1/rewards/sessions` | Create reward session | Later |
| POST | `/api/v1/rewards/callback` | Verified provider callback | Later |
| POST | `/api/v1/payments/webhook` | Provider/payment event handling | Later |

Do not expose endpoints simply because they are listed. Bot-first MVP can use application services without public download endpoints.

## 3. Error envelope

```json
{
  "error": {
    "code": "UNSUPPORTED_URL",
    "message": "That link is not supported yet.",
    "request_id": "uuid"
  }
}
```

Do not return stack traces, raw yt-dlp output, local paths, internal IPs or secrets.

Stable error codes include:
`INVALID_URL`, `UNSUPPORTED_PLATFORM`, `UNSUPPORTED_CONTENT`, `PRIVATE_OR_RESTRICTED_CONTENT`, `URL_BLOCKED`, `QUOTA_EXHAUSTED`, `FILE_TOO_LARGE`, `DURATION_LIMIT`, `PROCESSING_TIMEOUT`, `SOURCE_UNAVAILABLE`, `TELEGRAM_DELIVERY_FAILED`, `TEMPORARY_FAILURE`, `INTERNAL_ERROR`.

## 4. Telegram commands and interaction

MVP:
- `/start`: welcome, public-content limitations, supported platforms.
- `/help`: supported URL types and usage guidance.
- `/status`: show current plan, today's included usage, reward credits if enabled, and subscription end date if active.
- URL message: create a download request.

Optional later:
- `/premium`: subscription information and Telegram Stars purchase flow, only after price/allowance are approved.
- `/cancel`: cancel a cancellable queued job.
- `/support`: support contact/configuration.

Bot should acknowledge accepted work promptly. Do not block update handling while yt-dlp or FFmpeg runs. Handle duplicate Telegram updates idempotently.

## 5. Bot message states

- Accepted: “Your video is queued.”
- Processing: concise progress updates only if they provide value; throttle edits.
- Success: send media and a concise completion message if needed.
- Quota exhausted: explain included allowance is used and explain reward/premium options only when those features are configured and enabled.
- Failure: user-safe message mapped from stable error code.

Never tell users a download succeeded until Telegram confirms delivery.

## 6. URL intake contract

- Accept only `http` and `https`.
- Normalize hostname using IDNA and lowercase.
- Match exact platform host allowlists and explicit supported URL patterns.
- Reject credentials embedded in URL, nonstandard ports unless explicitly required, IP-literal hosts, localhost, private/link-local/multicast/reserved addresses.
- Validate every redirect destination; resolve DNS and block prohibited ranges. Protect against DNS rebinding by validating resolved addresses at connection time or using a controlled egress strategy.
- Do not accept arbitrary user-supplied extractor options, local paths or file schemes.
- Strip or redact sensitive query parameters in logs.
- Canonicalization must preserve required source identifiers while removing irrelevant tracking parameters only when safe.

## 7. Telegram Mini App security (later)

Validate `initData` signature server-side using Telegram's documented algorithm and enforce freshness/replay policy. Never trust a user ID supplied separately by the browser. The Mini App is not a trusted authority for reward completion or entitlement.

## 8. Provider callbacks (later)

- Authenticate callback signatures or provider-specific verification.
- Verify event authenticity server-side.
- Enforce timestamp/replay window.
- Unique provider event/transaction IDs.
- Idempotent processing with durable event record.
- Acknowledge only after durable processing or safe enqueue.
