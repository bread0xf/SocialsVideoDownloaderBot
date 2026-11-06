import asyncio

import pytest

from backend.core.errors import ErrorCode, UrlValidationError
from backend.platforms import urls


@pytest.mark.parametrize(
    ("raw", "expected_url", "platform", "content_type", "source_id"),
    [
        (
            "https://www.tiktok.com/@creator/video/1234567890?is_from_webapp=1",
            "https://www.tiktok.com/@creator/video/1234567890",
            "tiktok",
            "public_video",
            "1234567890",
        ),
        (
            "https://vt.tiktok.com/ZSabcdef/",
            "https://vt.tiktok.com/ZSabcdef",
            "tiktok",
            "public_video",
            "ZSabcdef",
        ),
        (
            "https://youtu.be/dQw4w9WgXcQ?si=tracking",
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "youtube",
            "public_video",
            "dQw4w9WgXcQ",
        ),
        (
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL123&t=10",
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "youtube",
            "public_video",
            "dQw4w9WgXcQ",
        ),
        (
            "https://m.youtube.com/shorts/dQw4w9WgXcQ",
            "https://www.youtube.com/shorts/dQw4w9WgXcQ",
            "youtube",
            "public_short",
            "dQw4w9WgXcQ",
        ),
        (
            "https://www.instagram.com/reel/AbCdEf123/",
            "https://www.instagram.com/reel/AbCdEf123/",
            "instagram",
            "public_reel",
            "AbCdEf123",
        ),
        (
            "https://www.instagram.com/p/AbCdEf123/?utm_source=ig_web",
            "https://www.instagram.com/p/AbCdEf123/",
            "instagram",
            "public_video_post",
            "AbCdEf123",
        ),
        (
            "https://fb.watch/AbCdEf123/",
            "https://fb.watch/AbCdEf123/",
            "facebook",
            "public_video",
            "AbCdEf123",
        ),
        (
            "https://www.facebook.com/watch/?v=1234567890",
            "https://www.facebook.com/watch/?v=1234567890",
            "facebook",
            "public_video",
            "1234567890",
        ),
        (
            "https://www.facebook.com/reel/1234567890",
            "https://www.facebook.com/reel/1234567890/",
            "facebook",
            "public_reel",
            "1234567890",
        ),
        (
            "https://www.facebook.com/share/v/AbCdEf123/",
            "https://www.facebook.com/share/v/AbCdEf123/",
            "facebook",
            "public_video",
            "AbCdEf123",
        ),
        (
            "https://www.facebook.com/SomePage/videos/1234567890/",
            "https://www.facebook.com/SomePage/videos/1234567890/",
            "facebook",
            "public_video_post",
            "1234567890",
        ),
        (
            "https://WWW.YOUTUBE.COM/watch?v=dQw4w9WgXcQ",
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "youtube",
            "public_video",
            "dQw4w9WgXcQ",
        ),
        (
            "https://www.tiktok.com/t/ZTabc12345/",
            "https://www.tiktok.com/t/ZTabc12345/",
            "tiktok",
            "public_video",
            "ZTabc12345",
        ),
        (
            "https://m.tiktok.com/v/1234567890.html",
            "https://m.tiktok.com/v/1234567890.html",
            "tiktok",
            "public_video",
            "1234567890",
        ),
        (
            "https://www.instagram.com/share/reel/AbCdEf123/",
            "https://www.instagram.com/reel/AbCdEf123/",
            "instagram",
            "public_reel",
            "AbCdEf123",
        ),
        (
            "https://www.instagram.com/reels/AbCdEf123/",
            "https://www.instagram.com/reel/AbCdEf123/",
            "instagram",
            "public_reel",
            "AbCdEf123",
        ),
        (
            "https://www.youtube.com/embed/dQw4w9WgXcQ",
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "youtube",
            "public_video",
            "dQw4w9WgXcQ",
        ),
        (
            "https://www.youtube.com/live/dQw4w9WgXcQ",
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "youtube",
            "public_video",
            "dQw4w9WgXcQ",
        ),
        (
            "https://music.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "youtube",
            "public_video",
            "dQw4w9WgXcQ",
        ),
        (
            "https://www.facebook.com/reels/1234567890",
            "https://www.facebook.com/reel/1234567890/",
            "facebook",
            "public_reel",
            "1234567890",
        ),
        (
            "https://www.facebook.com/share/r/AbCdEf123/",
            "https://www.facebook.com/share/r/AbCdEf123/",
            "facebook",
            "public_video",
            "AbCdEf123",
        ),
    ],
)
def test_normalize_url_canonicalizes_supported_links(
    raw: str,
    expected_url: str,
    platform: str,
    content_type: str,
    source_id: str,
) -> None:
    result = urls.normalize_url(raw)

    assert result.url == expected_url
    assert result.platform == platform
    assert result.content_type == content_type
    assert result.source_id == source_id


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        ("", ErrorCode.INVALID_URL),
        ("ftp://youtube.com/watch?v=dQw4w9WgXcQ", ErrorCode.INVALID_URL),
        ("javascript:alert(1)", ErrorCode.INVALID_URL),
        ("https://youtube.com:8443/watch?v=dQw4w9WgXcQ", ErrorCode.URL_BLOCKED),
        ("https://user:pass@youtube.com/watch?v=dQw4w9WgXcQ", ErrorCode.URL_BLOCKED),
        ("http://127.0.0.1/watch?v=dQw4w9WgXcQ", ErrorCode.URL_BLOCKED),
        ("http://[::1]/watch?v=dQw4w9WgXcQ", ErrorCode.URL_BLOCKED),
        ("https://youtube.com.evil.example/watch?v=dQw4w9WgXcQ", ErrorCode.UNSUPPORTED_PLATFORM),
        ("https://vimeo.com/123456789", ErrorCode.UNSUPPORTED_PLATFORM),
        ("https://youtube.com/playlist?list=PL123", ErrorCode.UNSUPPORTED_CONTENT),
        ("https://youtube.com/watch?v=short", ErrorCode.UNSUPPORTED_CONTENT),
        ("https://youtube.com/watch?v=dQw4w9WgXcQ&v=other", ErrorCode.UNSUPPORTED_CONTENT),
        ("https://www.instagram.com/stories/user/123/", ErrorCode.UNSUPPORTED_CONTENT),
        ("https://www.tiktok.com/@creator", ErrorCode.UNSUPPORTED_CONTENT),
        ("https://youtube.com/../watch?v=dQw4w9WgXcQ", ErrorCode.INVALID_URL),
        ("https://youtube.com/%2e%2e/watch?v=dQw4w9WgXcQ", ErrorCode.INVALID_URL),
        ("https://youtube.com\\watch?v=dQw4w9WgXcQ", ErrorCode.INVALID_URL),
        ("https://www.tiktok.com/t/", ErrorCode.UNSUPPORTED_CONTENT),
        ("https://www.youtube.com/live/short", ErrorCode.UNSUPPORTED_CONTENT),
        ("https://www.instagram.com/share/reel/", ErrorCode.UNSUPPORTED_CONTENT),
    ],
)
def test_normalize_url_rejects_bad_links(raw: str, code: ErrorCode) -> None:
    with pytest.raises(UrlValidationError) as exc_info:
        urls.normalize_url(raw)

    assert exc_info.value.code == code


def test_normalize_url_rejects_overlong_input() -> None:
    with pytest.raises(UrlValidationError) as exc_info:
        urls.normalize_url("https://youtube.com/watch?v=" + "a" * 2048)

    assert exc_info.value.code == ErrorCode.INVALID_URL


class _FakeLoop:
    def __init__(self, infos: list[tuple[object, ...]] | OSError) -> None:
        self._infos = infos

    async def getaddrinfo(
        self, host: str, port: int | None, *, type: int
    ) -> list[tuple[object, ...]]:
        if isinstance(self._infos, OSError):
            raise self._infos
        return self._infos


def _patch_loop(monkeypatch: pytest.MonkeyPatch, loop: _FakeLoop) -> None:
    monkeypatch.setattr(asyncio, "get_running_loop", lambda: loop)


async def test_resolve_public_addresses_allows_global_addresses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_loop(
        monkeypatch,
        _FakeLoop(
            [
                (2, 1, 6, "", ("93.184.216.34", 0)),
                (10, 1, 6, "", ("2606:2800:220:1:248:1893:25c8:1946", 0)),
            ]
        ),
    )

    addresses = await urls.resolve_public_addresses("youtube.com")

    assert set(addresses) == {"93.184.216.34", "2606:2800:220:1:248:1893:25c8:1946"}


@pytest.mark.parametrize(
    "address",
    ["127.0.0.1", "10.0.0.5", "169.254.169.254", "192.168.1.10", "::1", "fc00::1"],
)
async def test_resolve_public_addresses_blocks_non_global_addresses(
    monkeypatch: pytest.MonkeyPatch, address: str
) -> None:
    _patch_loop(monkeypatch, _FakeLoop([(2, 1, 6, "", (address, 0))]))

    with pytest.raises(UrlValidationError) as exc_info:
        await urls.resolve_public_addresses("youtube.com")

    assert exc_info.value.code == ErrorCode.URL_BLOCKED


async def test_resolve_public_addresses_maps_dns_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_loop(monkeypatch, _FakeLoop(OSError("dns failure")))

    with pytest.raises(UrlValidationError) as exc_info:
        await urls.resolve_public_addresses("youtube.com")

    assert exc_info.value.code == ErrorCode.SOURCE_UNAVAILABLE


async def test_resolve_public_addresses_rejects_empty_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_loop(monkeypatch, _FakeLoop([]))

    with pytest.raises(UrlValidationError) as exc_info:
        await urls.resolve_public_addresses("youtube.com")

    assert exc_info.value.code == ErrorCode.URL_BLOCKED


def test_validate_extracted_url_allows_same_platform_redirect() -> None:
    original = urls.normalize_url("https://vt.tiktok.com/ZSabc123/")

    urls.validate_extracted_url(
        original,
        "https://www.tiktok.com/@creator/video/1234567890",
    )


def test_validate_extracted_url_allows_missing_url() -> None:
    original = urls.normalize_url("https://youtu.be/dQw4w9WgXcQ")

    urls.validate_extracted_url(original, None)


@pytest.mark.parametrize(
    "extracted_url",
    [
        "https://www.facebook.com/watch/?v=1234567890",
        "https://evil.example/watch?v=dQw4w9WgXcQ",
        "https://www.instagram.com/accounts/login/",
    ],
)
def test_validate_extracted_url_rejects_cross_platform_or_unlisted_urls(
    extracted_url: str,
) -> None:
    original = urls.normalize_url("https://youtu.be/dQw4w9WgXcQ")

    with pytest.raises(UrlValidationError) as exc_info:
        urls.validate_extracted_url(original, extracted_url)

    assert exc_info.value.code == ErrorCode.URL_BLOCKED
