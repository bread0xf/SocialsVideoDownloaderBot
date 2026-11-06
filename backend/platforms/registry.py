from dataclasses import dataclass

from backend.core.errors import AppError, ErrorCode

_ACCEPTING_STATUSES = frozenset({"active", "degraded"})


@dataclass(frozen=True, slots=True)
class Platform:
    key: str
    display_name: str
    status: str
    content_types: frozenset[str]

    @property
    def is_accepting(self) -> bool:
        return self.status in _ACCEPTING_STATUSES


DEFAULT_PLATFORMS: tuple[Platform, ...] = (
    Platform("tiktok", "TikTok", "active", frozenset({"public_video"})),
    Platform(
        "instagram",
        "Instagram",
        "active",
        frozenset({"public_reel", "public_video_post"}),
    ),
    Platform(
        "youtube",
        "YouTube",
        "active",
        frozenset({"public_video", "public_short"}),
    ),
    Platform(
        "facebook",
        "Facebook",
        "active",
        frozenset({"public_video_post", "public_reel", "public_video"}),
    ),
)


class PlatformRegistry:
    def __init__(self, platforms: tuple[Platform, ...] = DEFAULT_PLATFORMS) -> None:
        self._platforms = {platform.key: platform for platform in platforms}

    def get(self, key: str) -> Platform | None:
        return self._platforms.get(key)

    def all(self) -> tuple[Platform, ...]:
        return tuple(self._platforms.values())

    def require_accepting(self, key: str, content_type: str) -> Platform:
        platform = self.get(key)
        if platform is None:
            raise AppError(ErrorCode.UNSUPPORTED_PLATFORM, "That platform is not supported.")
        if platform.status == "maintenance":
            raise AppError(
                ErrorCode.SOURCE_UNAVAILABLE,
                f"{platform.display_name} is temporarily under maintenance. Try again later.",
            )
        if not platform.is_accepting:
            raise AppError(ErrorCode.UNSUPPORTED_PLATFORM, "That platform is not supported.")
        if content_type not in platform.content_types:
            raise AppError(ErrorCode.UNSUPPORTED_CONTENT, "That link type is not supported.")
        return platform


platform_registry = PlatformRegistry()
