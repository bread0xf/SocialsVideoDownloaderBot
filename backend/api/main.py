import uvicorn

from backend.core.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "backend.api.app:app",
        host="0.0.0.0",  # noqa: S104 - container must listen on all interfaces
        port=settings.port,
        log_level=settings.log_level.lower(),
    )
