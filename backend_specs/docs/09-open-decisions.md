# 09 — Open Decisions and Implementation Gates

These items were not finalized in the recorded decisions. Agents must not guess or hardcode them.

| ID | Decision | Current status | Implementation handling |
|---|---|---|---|
| OD-01 | Premium monthly price (Telegram Stars) | Open | Do not show a purchase price or create live invoices until approved. |
| OD-02 | Premium daily included-download allowance | Open | Keep nullable/configurable; do not assume unlimited or a numeric quota. |
| OD-03 | Rewarded-ad provider | Open | Implement provider interface only; keep reward earning disabled. |
| OD-04 | Reward credit expiry | Open | Do not invent expiry; ledger supports nullable expiry. |
| OD-05 | Daily rewarded-ad cap / reward quantity | Open | Keep provider/config policy unset; no client-side grants. |
| OD-06 | Free file-size, duration and concurrency ceilings | Open | Provide conservative deployment configuration; require operator values before production. |
| OD-07 | Telegram delivery upload ceiling and Bot API deployment | Verify at deployment | Verify current official Telegram limits and selected hosted/local Bot API mode. |
| OD-08 | Sponsor placement policy/content source | Partially specified | Free may receive bot-managed placements; no campaign billing/targeting policy yet. |

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

The first free downloader vertical slice can proceed without OD-01 through OD-05 if monetization interfaces are isolated and reward/premium purchase features remain disabled. Production launch still requires operational limits and Telegram upload configuration to be explicitly set and verified.
