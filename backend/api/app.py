from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.api.routes.health import router as health_router
from backend.api.routes.platforms import router as platforms_router
from backend.core.config import Settings, get_settings
from backend.core.logging import configure_logging
from backend.database.redis import build_redis
from backend.database.session import build_engine, build_session_factory


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    engine = build_engine(settings)
    redis = build_redis(settings)
    app.state.db_engine = engine
    app.state.redis = redis
    app.state.session_factory = build_session_factory(engine)
    try:
        yield
    finally:
        await redis.aclose()
        await engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or get_settings()
    configure_logging(resolved.log_level, resolved.log_json)

    app = FastAPI(
        title="SocialsVideoDownloaderBot API",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = resolved
    app.include_router(health_router)
    app.include_router(platforms_router)
    return app


app = create_app()
