# Development Standards

## Language and tooling

- Python 3.13+ (`requires-python = ">=3.13"`), managed with `uv` and a committed `uv.lock`.
- `python-telegram-bot` for Telegram interaction.
- FastAPI for API routes.
- Pydantic Settings for validated configuration.
- SQLAlchemy 2.x async with asyncpg, plus Alembic migrations.
- PostgreSQL for durable state; Redis + ARQ for background jobs and cron maintenance.
- yt-dlp behind the platform adapter; FFmpeg/FFprobe for media validation and preparation.
- Deno 2.3+ in the image for yt-dlp JavaScript challenge solving.
- Ruff (lint and format), mypy (typed code), pytest and pytest-asyncio.
- Docker and Docker Compose for local infrastructure.

Pin dependencies in `pyproject.toml` and commit the lockfile. Review extractor and media-tool security advisories before upgrading.

## Code organization

- Keep domain logic framework-independent.
- Handlers and routes are thin transport adapters; application services orchestrate transactions.
- Keep extraction behind `backend/platforms/adapters/`; do not import yt-dlp into domain code.
- Keep infrastructure concerns in `backend/database/`, `backend/storage/` and `backend/core/`.
- Avoid circular imports and hidden global mutable state.

## Async and subprocesses

- Use async APIs for network, database and Redis operations.
- Do not block Telegram update processing with extraction or FFmpeg.
- Use subprocess argument arrays, never shell interpolation.
- Apply timeouts, cancellation and process-group kills; cap captured output.
- Give each job an isolated workspace and remove it in a `finally` block.

## Configuration

- Validate configuration at startup with Pydantic Settings.
- Keep development/test/production behavior explicit. `APP_ENV=production` currently requires a Telegram token for every process; do not use production mode for the API until that validation is made role-specific.
- Accept standard PostgreSQL URLs and normalize them to the asyncpg driver.
- Document every environment variable in `.env.example` with safe placeholders only.
- Never commit secrets, tokens, cookies or real connection strings.

## Testing

- Unit tests: domain rules, URL validators, format selection, quota policies, bot v0 behavior.
- Integration tests: PostgreSQL transactions, quota locking, outbox dispatch, ARQ processing, Telegram delivery adapter, media processing.
- Contract tests: platform adapters and provider callbacks when added.
- End-to-end tests: simulated Telegram update through successful and failed delivery.
- Do not make the default suite depend on live social-media URLs; live extraction is gated by `SVDB_LIVE_EXTRACTION=1`.
- Include concurrency, duplicate-update and idempotency tests.

Integration tests need PostgreSQL. Set `TEST_DATABASE_URL` to an isolated database, or let the suite create a temporary database on the server in `DATABASE_URL`. They skip when PostgreSQL is unavailable.

## Quality gates

Before merging:

- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run mypy backend apps`
- `uv run pytest -q`
- Migrations apply from an empty database.
- No secrets or sensitive fixtures in the repository, logs or snapshots.
- Documentation updated when behavior or decisions change.
- Security impact and failure behavior reviewed.

## Git and review

- Small, focused commits with descriptive branch names.
- Do not commit generated media, cache artifacts, `.env`, secrets or local database files.
- PR description includes intent, design, tests, migration impact and operational notes.
- The hosted development environment deploys from the `dev` branch; keep `main` stable.
