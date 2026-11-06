# 01 — Product and Architecture Specification

## 1. Product definition

A public Telegram bot that accepts supported social-media video URLs, extracts publicly accessible media, automatically selects an eligible quality and delivers the media through Telegram.

MVP platform/content matrix:

| Platform | Supported content |
|---|---|
| TikTok | Public videos |
| Instagram | Public Reels, video posts, carousel videos |
| YouTube | Public videos and Shorts |
| Facebook | Public video posts and Reels |

Support is best-effort within tested compatibility. A platform being listed does not guarantee every URL, region, media type or extractor path will work. The platform registry must expose operational state: `active`, `degraded`, `maintenance`, `unsupported`.

## 2. Explicit exclusions

- Private/restricted content.
- Authentication or access-control bypass.
- DRM circumvention.
- Asking for or storing social-media passwords or session cookies.
- Arbitrary file URLs or unrestricted URL fetching.
- External download links in MVP.
- User-selected output format/quality in the initial flow.

The service must respect applicable platform restrictions and content rights.

## 3. User experience

1. User starts bot; bot explains supported platforms and public-content limitation.
2. User sends a URL.
3. Bot validates URL and reports unsupported/invalid URLs clearly.
4. Bot creates a persistent download job and responds with a processing acknowledgement.
5. Worker extracts metadata and formats, applies entitlement ceiling and operational limits, processes if required, then sends media through Telegram.
6. Bot reports success or a safe actionable failure. Usage is committed only after successful Telegram delivery.

No Mini App is required for the first downloader vertical slice.

## 4. Quality policy

Quality is selected automatically.

| Resolution | Free | Premium |
|---|---:|---:|
| 360p | Yes | Yes |
| 480p | Yes | Yes |
| 720p | No | Yes |
| 1080p | No | Yes |
| 1440p | No | Yes |
| 2160p / 4K | No | Yes |

These are ceilings, not guarantees. Source availability, Telegram upload constraints, processing capability and configured resource limits still apply.

Selection algorithm:
1. Inspect available formats.
2. Filter by entitlement ceiling.
3. Exclude formats exceeding configured duration, size, codec or processing limits.
4. Prefer highest remaining resolution.
5. Prefer a compatible combined audio/video format when quality is otherwise equivalent.
6. Merge separate streams with FFmpeg when necessary.
7. Validate final output using FFprobe before delivery.

Free ceiling is 480p. Premium ceiling is 4K. Do not infer Premium daily allowance or price.

## 5. Delivery and caching

- Deliver directly through Telegram.
- Use video delivery when suitable; document delivery is an allowed fallback.
- Check configured upload limits before attempting delivery. Hosted Bot API limits must be verified against current Telegram documentation before launch.
- Persist reusable Telegram `file_id` after successful delivery.
- A cached Telegram `file_id` never bypasses current entitlement checks.
- No external link delivery in MVP.

Storage has two layers:
- Per-job temporary workspace: delete on completion or definitive failure.
- Processed media cache: configurable storage quota; hard retention ceiling of 24 hours.

Cache only verified successful outputs. Cache key must include normalized source identity, selected output profile, processing version and relevant source metadata. Do not share private/restricted content across users. Recheck entitlement before serving cached media.

Initial storage is local disk behind a storage abstraction. Object storage is future scope.

## 6. Architecture

Modular monolith, one codebase, separately runnable processes:

| Process | Responsibility |
|---|---|
| Bot | Telegram updates and user interaction |
| API | Health, Mini App endpoints when introduced, verified provider callbacks |
| Worker | Extraction, processing and delivery |
| Scheduler | Retention cleanup, subscription expiry and scheduled operations |

Use distributed coordination for scheduled tasks. PostgreSQL is authoritative. Redis is coordination/queue infrastructure, not the source of truth.

## 7. Module boundaries

`users`, `platforms`, `downloads`, `entitlements`, `usage`, `monetization`, `workers`, `api`, `database`, `storage`, `bot`.

Bot/API adapters call application services. Domain rules must not live in Telegram handlers, HTTP routes, or worker task wrappers. Keep yt-dlp types inside an adapter and expose normalized domain DTOs.

## 8. Platform adapter contract

A normalized extraction result should include, when available:
- platform key and canonical source URL;
- extractor/media identifier;
- title, duration, thumbnail;
- available formats, codecs, resolution and estimated size;
- audio/video stream relationships;
- safe diagnostic category (not raw sensitive extractor output).

Adapter operations should support URL recognition, metadata extraction, format listing and media acquisition. yt-dlp is the initial implementation, not a domain-level dependency.

## 9. Repository layout

```text
.
├── apps/
│   └── bot/
├── backend/
│   ├── core/
│   ├── users/
│   ├── platforms/
│   │   └── adapters/
│   ├── downloads/
│   ├── entitlements/
│   ├── usage/
│   ├── monetization/
│   ├── workers/
│   ├── api/
│   ├── database/
│   └── storage/
├── migrations/
├── tests/
│   ├── unit/
│   ├── integration/
│   └── e2e/
├── infrastructure/
├── docs/
├── compose.yaml
├── pyproject.toml
├── .env.example
└── README.md
```

Introduce payment, sponsor and Mini App implementation only when their roadmap phase begins. Do not create empty speculative modules.
