import httpx
import pytest

from backend.api.app import create_app
from backend.core.config import Settings


@pytest.mark.asyncio
async def test_live_endpoint() -> None:
    app = create_app(Settings(_env_file=None, app_env="test"))
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
