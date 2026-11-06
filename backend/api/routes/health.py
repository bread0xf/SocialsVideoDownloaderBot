from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

router = APIRouter(tags=["health"])


@router.get("/health/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
async def ready(request: Request) -> JSONResponse:
    checks: dict[str, str] = {"database": "ok", "redis": "ok"}
    healthy = True

    try:
        async with request.app.state.db_engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception:
        checks["database"] = "unavailable"
        healthy = False

    try:
        await request.app.state.redis.ping()
    except Exception:
        checks["redis"] = "unavailable"
        healthy = False

    payload: dict[str, Any] = {
        "status": "ok" if healthy else "unavailable",
        "checks": checks,
    }
    return JSONResponse(payload, status_code=200 if healthy else 503)
