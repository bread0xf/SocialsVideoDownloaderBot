# Development Standards

## Language and tooling

- Python 3.12+ (confirm exact runtime support before pinning).
- `python-telegram-bot` for Telegram interaction.
- FastAPI for API and provider callbacks.
- Pydantic for boundary validation/settings.
- SQLAlchemy 2.x (proposed) and Alembic for persistence/migrations.
- PostgreSQL for durable state.
- Redis + ARQ for background processing.
- yt-dlp behind an adapter; FFmpeg for media processing.
- pytest, Ruff and optional mypy/pyright.
- Docker Compose for local development.

Pin dependencies and commit a lockfile. Recheck current compatible versions during implementation; do not assume this document establishes latest versions.

## Code organization

- Keep domain logic framework-independent.
- Handlers/controllers should be thin transport adapters.
- Use application services for orchestration.
- Define interfaces around extraction, delivery, billing and reward providers.
- Keep infrastructure-specific code in infrastructure/adapters.
- Avoid circular imports and hidden global mutable state.

## Async and subprocesses

- Use async APIs for network and database operations where supported.
- Do not block Telegram update processing with extraction or FFmpeg.
- Use subprocess argument arrays, never shell interpolation.
- Apply timeouts, cancellation handling and resource limits.
- Ensure subprocesses and temporary workspaces are cleaned up.

## Configuration

- Validate configuration at startup.
- Separate development/test/production settings.
- No secrets committed to the repository.
- Document every environment variable in `.env.example` with safe placeholders only.

## Testing

- Unit tests: domain rules, URL validators, format selection, quota policies.
- Integration tests: PostgreSQL transactions, Redis queue, outbox, worker and Telegram delivery adapter.
- Contract tests: platform adapters and provider callbacks.
- End-to-end tests: simulated Telegram update through successful/failed delivery.
- Use mocks/fixtures; do not make tests depend on live social media URLs.
- Include concurrency and idempotency tests.

## Quality gates

Before merging:
- Ruff format/check passes.
- Test suite passes.
- Migrations apply from an empty database and upgrade existing schema.
- No secrets or sensitive fixtures.
- Documentation updated.
- Security impact and failure behavior reviewed.

## Git and review

- Small, focused commits.
- Descriptive branch/commit names.
- No generated media, cache artifacts, secrets or local database files.
- PR description includes intent, design, tests, migration impact and operational notes.
