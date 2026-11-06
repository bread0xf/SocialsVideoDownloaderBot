from fastapi import APIRouter
from pydantic import BaseModel

from backend.platforms.registry import platform_registry

router = APIRouter(prefix="/api/v1", tags=["platforms"])


class PlatformResponse(BaseModel):
    key: str
    display_name: str
    status: str
    content_types: list[str]


@router.get("/platforms", response_model=list[PlatformResponse])
async def list_platforms() -> list[PlatformResponse]:
    return [
        PlatformResponse(
            key=platform.key,
            display_name=platform.display_name,
            status=platform.status,
            content_types=sorted(platform.content_types),
        )
        for platform in platform_registry.all()
        if platform.is_accepting
    ]
