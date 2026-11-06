import pytest

from backend.core.errors import AppError, ErrorCode
from backend.platforms.registry import DEFAULT_PLATFORMS, Platform, PlatformRegistry


def test_default_registry_accepts_supported_content() -> None:
    platform = PlatformRegistry().require_accepting("youtube", "public_short")

    assert platform.key == "youtube"


def test_registry_rejects_unknown_platform() -> None:
    with pytest.raises(AppError) as exc_info:
        PlatformRegistry().require_accepting("vimeo", "public_video")

    assert exc_info.value.code == ErrorCode.UNSUPPORTED_PLATFORM


def test_registry_rejects_unsupported_content_type() -> None:
    with pytest.raises(AppError) as exc_info:
        PlatformRegistry().require_accepting("tiktok", "public_reel")

    assert exc_info.value.code == ErrorCode.UNSUPPORTED_CONTENT


def test_maintenance_platform_reports_availability_error() -> None:
    registry = PlatformRegistry(
        (
            Platform(
                "youtube",
                "YouTube",
                "maintenance",
                frozenset({"public_video"}),
            ),
        )
    )

    with pytest.raises(AppError) as exc_info:
        registry.require_accepting("youtube", "public_video")

    assert exc_info.value.code == ErrorCode.SOURCE_UNAVAILABLE


def test_disabled_platform_is_not_accepting() -> None:
    registry = PlatformRegistry(
        (
            Platform(
                "youtube",
                "YouTube",
                "disabled",
                frozenset({"public_video"}),
            ),
        )
    )

    with pytest.raises(AppError) as exc_info:
        registry.require_accepting("youtube", "public_video")

    assert exc_info.value.code == ErrorCode.UNSUPPORTED_PLATFORM


def test_default_platforms_cover_mvp() -> None:
    assert {platform.key for platform in DEFAULT_PLATFORMS} == {
        "tiktok",
        "instagram",
        "youtube",
        "facebook",
    }
