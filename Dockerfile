FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl ffmpeg unzip \
    && rm -rf /var/lib/apt/lists/*

# Deno runs yt-dlp-ejs JavaScript challenge solvers (required for YouTube).
ARG DENO_VERSION=v2.9.6
RUN curl -fsSL https://deno.land/install.sh | DENO_INSTALL=/usr/local sh -s "${DENO_VERSION}"

COPY --from=ghcr.io/astral-sh/uv:0.12.15 /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
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
