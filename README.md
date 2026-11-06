# SocialsVideoDownloaderBot

A Telegram bot for downloading publicly accessible videos from supported social platforms and delivering them to users in Telegram.

## Product snapshot

- **MVP platforms:** TikTok, Instagram, YouTube, Facebook
- **Access policy:** Public content only; no login, private-content access, DRM circumvention, or access-control bypass
- **Delivery:** Telegram
- **Commercial model:** Freemium + monthly Premium
- **Free allowance:** 5 successful downloads per user per day
- **Rewarded allowance:** 1 additional download per successfully verified rewarded-ad event
- **Free quality:** Proposed initial ceiling of 480p; **release decision still required**
- **Premium quality:** Best supported source quality, up to 4K where source, processing, Telegram and deployment limits allow
- **Architecture:** Python modular monolith, deployed as separate bot/API/worker/scheduler processes from one codebase

## Proposed stack

Python, `python-telegram-bot`, FastAPI, yt-dlp behind a replaceable extraction interface, FFmpeg, PostgreSQL, Redis, ARQ, Pydantic, Alembic, pytest, Ruff and Docker Compose.

## Repository map

```text
.
├── AGENTS.md
├── README.md
└── docs/
    ├── product/
    ├── architecture/
    ├── engineering/
    ├── operations/
    └── project/
```

## Getting started

This archive is the specification and agent hand-off pack, not an implemented application. No runtime code, credentials, deployment secrets, or production configuration are included.

1. Read `AGENTS.md`.
2. Read `docs/product/product-requirements.md` and `docs/project/unresolved-decisions.md`.
3. Review architecture and security documents.
4. Resolve release-blocking decisions before production launch.
5. Implement incrementally with tests and migrations.

## Important boundary

The bot must only process content that is publicly accessible through supported platform mechanisms. Platform terms, copyright rules, local law, and Telegram policies must be reviewed before launch. A technically downloadable URL is not, by itself, proof that the content may lawfully be downloaded or redistributed.

## Document status

These documents define the proposed MVP and implementation constraints. Items marked **OPEN**, **PROPOSED**, or **VERIFY** require confirmation. Do not silently convert them into settled product requirements.
