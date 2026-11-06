# 09 — Open Decisions and Implementation Gates

These items were not finalized in the recorded decisions. Agents must not guess or hardcode them.

| ID | Decision | Current status | Implementation handling |
|---|---|---|---|
| OD-01 | Premium monthly price (Telegram Stars) | Resolved 2026-11-06 — 150 Stars per 30-day subscription | Invoice for 150 Stars. Telegram subscription period is fixed at 2,592,000 seconds (30 days); verify the live minimum/limits at billing implementation. |
| OD-02 | Premium daily included-download allowance | Resolved 2026-11-06 — 20 per `Africa/Lagos` day | Set `premium_daily_limit=20`. The premium plan row may stay nullable and fall back to configuration. |
| OD-03 | Rewarded-ad provider | Partially resolved 2026-11-06 — ads are delivered as bot-managed chat/sponsor messages; no official Telegram rewarded-ad API exists | Reward granting must remain server-side: one-time token, authenticated callback, replay protection. Provider interface stays; exact ad delivery mechanism pending (see note). |
| OD-04 | Reward credit expiry | Partially resolved — one ad grants exactly one extra download, consumed after the included allowance | Expiry not specified by owner. Proposed: credit expires at the end of the `Africa/Lagos` quota day it was earned. Pending confirmation. |
| OD-05 | Daily rewarded-ad cap / reward quantity | Open — reward quantity resolved (1 download per ad); daily cap open | Proposed development default: 10 rewarded downloads per user per Lagos day. Owner must approve before enabling rewards. |
| OD-06 | Free file-size, duration and concurrency ceilings | Resolved 2026-11-06 — free 48 MiB / 10 min / 1 job; Premium 1.9 GB / 30 min / 2 jobs; worker and timeout values approved | See approved limits below. Keep all values configurable. |
| OD-07 | Telegram delivery upload ceiling and Bot API deployment | Verified 2026-11-06 — see limits below | Cloud Bot API: 50 MB upload / 20 MB download. Local Bot API server with `--local`: 2000 MB upload. Recommendation: local Bot API for Premium 4K; cloud-only deployments cap every delivery at 48 MiB. |
| OD-08 | Sponsor placement policy/content source | Partially resolved 2026-11-06 — free users only, one placement after each successful delivery; moderation deferred to the next phase | Free users receive one bot-managed placement per successful download, after delivery. No PII or preference tracking. Content moderation, targeting and campaign billing remain open. |

## Resolved values (owner-approved 2026-11-06)

### OD-01 — Premium price

- 150 Telegram Stars per month.
- Telegram Stars subscriptions use a fixed 30-day period (2,592,000 seconds); there is no weekly/annual option.
- Maximum subscription price allowed by Telegram is 10,000 Stars; 150 is well within it.
- Developer payout is set by Telegram (reported around USD 0.013 per Star in 2026; verify before publishing revenue assumptions).
- Do not display a price or create live invoices until the billing module is implemented and the current Telegram terms are re-verified.

### OD-02 — Premium allowance

- 20 included successful downloads per `Africa/Lagos` calendar day.
- Included allowance is consumed before rewarded credits.
- Configure through `premium_daily_limit=20`; do not hardcode in handlers.

### OD-03 / OD-04 / OD-05 — Rewarded ads

Owner direction:

- Ads are delivered through Telegram as bot-managed chat/sponsor messages.
- A user watches an ad and receives **one additional download**.
- A user may earn repeatedly (“it could continue like that”), subject to the still-open daily cap.

Constraints that remain in force:

- Telegram has **no official rewarded-ad API for bots**. Official Sponsored Messages in bots are an advertising/revenue product and do not emit a per-user completion event. A rewarded flow must therefore be built as a bot-managed placement or through a third-party provider.
- Never grant a credit from a client-supplied “ad watched” claim alone.
- If the ad is a bot-managed message: issue a single-use, server-side token with the ad message, require an authenticated `callback_query` from Telegram no earlier than a minimum dwell time, and write the credit to the append-only reward ledger exactly once per token.
- If a third-party provider is selected: require server-to-server postback authentication, one provider transaction ID per grant, and replay protection.
- Credits consume after the included allowance and count only toward successful deliveries.
- Proposed expiry: end of the Lagos quota day the credit was earned. Pending owner confirmation.
- Proposed daily cap: 10 rewarded downloads per user per Lagos day. Pending owner approval; keep configurable and fail closed.

## Approved limits for OD-06 (owner-approved 2026-11-06)

These are conservative operational defaults, not published product promises.

### Free plan

| Control | Proposed value |
|---|---|
| Maximum resolution | 480p (locked) |
| Maximum source duration | 600 seconds (10 minutes) |
| Maximum output size | 48 MiB (50,331,648 bytes), safely below the 50 MB cloud Bot API cap |
| Concurrent active jobs per user | 1 |
| Daily included downloads | 5 (locked) |

### Premium plan

| Control | Proposed value |
|---|---|
| Maximum resolution | 2160p where source permits (locked) |
| Maximum source duration | 1800 seconds (30 minutes) |
| Maximum output size | 1.9 GB (1,900,000,000 bytes), below the 2000 MB local Bot API cap |
| Concurrent active jobs per user | 2 |
| Daily included downloads | 20 (approved) |

### Worker and processing controls

| Control | Proposed value | Rationale |
|---|---|---|
| `worker_concurrency` | 2 per worker container | ffmpeg/yt-dlp are CPU- and disk-heavy; scale out with more containers on larger hosts |
| Extractor metadata timeout | 60 seconds | `--skip-download` inspection should be fast |
| Download timeout | 900 seconds (15 minutes) | Includes fetching the largest Premium source |
| FFmpeg timeout | 600 seconds (10 minutes) | Covers remux and bounded transcode of a 30-minute source |
| ARQ job timeout | 1800 seconds (30 minutes) | Hard ceiling across all stages |
| Job max age | 7200 seconds (2 hours) | Stale-job reconciliation and retry window |
| Per-job disk budget | Free 256 MiB; Premium 6 GB | Source + output + temp headroom (~3× max output) |
| Cache cap | 50 GiB initial | 24-hour retention is locked; monitor and raise before launch if needed |
| Download attempts | 3 | Bounded retry for transient failures only |

## OD-07 — Telegram upload limits and oversized media

Verified 2026-11-06 from Telegram documentation and deployment notes:

- **Cloud Bot API (`api.telegram.org`):**
  - Bots can upload files up to **50 MB** through multipart `sendVideo`/`sendDocument`.
  - Sending by HTTP URL is capped at 20 MB (not used here).
  - Resending an existing file by `file_id` has **no size limit**.
  - `getFile` downloads are capped at 20 MB (not relevant to this bot).
  - Telegram states the 50 MB limit may change; re-verify at deployment.
- **Local Bot API server with `--local`:**
  - Uploads up to **2000 MB** (requires `api_id`/`api_hash` from `my.telegram.org`).
  - Downloads without a size limit; supports local file paths/file URIs.
- **Recommendation:** deploy a local Bot API server for Premium 4K delivery. A cloud-only deployment cannot deliver 4K or long videos above 48 MiB to any tier.

Handling sizes that exceed the selected ceiling:

1. Use yt-dlp format metadata to reject or avoid formats whose known size exceeds the budget before downloading.
2. Compute a bitrate budget from `max_bytes × 8 ÷ duration` minus the audio bitrate and select the highest rendition that fits.
3. Enforce the byte cap during download and during FFmpeg output; kill the process on overflow.
4. When the highest eligible rendition does not fit, step down resolution/bitrate within the plan ceiling; never upscale.
5. If the result still exceeds the cap, fail with the stable `FILE_TOO_LARGE` error, release the quota reservation, and do not write a commit ledger entry.
6. Never split the video, archive it, or send an external/link-only delivery in MVP.
7. Cache and reuse Telegram `file_id` values for identical output profiles to avoid re-uploads; still re-check entitlement before delivery.

## OD-08 — Sponsor placement policy (owner-approved 2026-11-06)

Sponsor placements are ads the bot itself injects into its chat messages. They are separate from Telegram's official ad platform.

Approved policy:

- **Audience:** free users only. Premium users never receive sponsor placements.
- **Frequency:** exactly one placement per successful free download.
- **Placement:** sent after the media file has been delivered, never before or instead of delivery. No placement on failed jobs.
- **Content and moderation:** allowed-content categories, review and takedown rules are deferred to the next phase, after the sponsor system works end to end. Until then, only operator-configured placements are allowed.
- **Premium purchase:** any free user can buy Premium through bot commands. Checkout and billing follow Telegram's Stars process; no separate web checkout.
- **Privacy:** no PII collection and no user-preference tracking. Placements are not personalized; do not store inferred interests or behavioral profiles.
- **Measurement:** aggregate impression/click counts only, without logging sensitive URLs or credentials.
- **Relationship to rewards:** a rewarded ad is a sponsor placement that grants one download credit, subject to the still-open daily cap and expiry decisions.

Still open: campaign billing, targeting rules (beyond “free users only”), and the content approval process.

## Already locked — do not reopen without explicit user instruction

- MVP platforms and public content types: TikTok public videos; Instagram public Reels/video posts/carousel videos; YouTube public videos/Shorts; Facebook public video posts/Reels.
- Public content only; no auth bypass, private content, DRM circumvention, password/cookie collection.
- Automatic quality selection; Free ceiling 480p; Premium ceiling 4K.
- Direct Telegram delivery; no external links in MVP.
- Python modular monolith; python-telegram-bot, FastAPI, yt-dlp, FFmpeg, PostgreSQL, Redis + ARQ, SQLAlchemy 2.x async, asyncpg, Alembic, Pydantic Settings, pytest, Ruff, Docker Compose, uv.
- Telegram-only identity.
- Daily quota reset at midnight `Africa/Lagos`.
- Included allowance consumed before rewarded credits.
- Paid access valid through `paid_through`.
- Media retention 24 hours.
- UUID internal IDs, Telegram IDs BIGINT, UTC timestamps, append-only ledgers, transactional outbox.

## Blocking policy

The first free downloader vertical slice can proceed without OD-03 through OD-06 if monetization interfaces are isolated and reward/premium purchase features remain disabled. Production launch still requires operational limits and Telegram upload configuration to be explicitly set and verified.
