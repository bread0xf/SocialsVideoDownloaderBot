FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.12.15 /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY backend ./backend
COPY apps ./apps
COPY migrations ./migrations
COPY alembic.ini ./

RUN uv sync --frozen --no-dev \
    && useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/storage \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

CMD ["svdb-api"]
