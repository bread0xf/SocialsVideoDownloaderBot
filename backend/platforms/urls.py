import asyncio
import ipaddress
import re
import socket
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

import idna

from backend.core.errors import ErrorCode, UrlValidationError

_YOUTUBE_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_YOUTUBE_SHORTS_PATH = re.compile(r"^/shorts/([A-Za-z0-9_-]{11})/?$")
_YOUTUBE_WATCH_PATH = re.compile(r"^/watch/?$")
_YOUTUBE_SHORT_PATH = re.compile(r"^/([A-Za-z0-9_-]{11})/?$")

_TIKTOK_VIDEO_PATH = re.compile(r"^/@([A-Za-z0-9._-]{1,64})/video/(\d{6,})/?$")
_TIKTOK_SHORT_PATH = re.compile(r"^/([A-Za-z0-9]{5,32})/?$")

_INSTAGRAM_PATH = re.compile(r"^/(reel|p|tv)/([A-Za-z0-9_-]{5,64})/?$")

_FACEBOOK_WATCH_PATH = re.compile(r"^/watch/?$")
_FACEBOOK_REEL_PATH = re.compile(r"^/reel/(\d{5,})/?$")
_FACEBOOK_VIDEO_PATH = re.compile(r"^/([A-Za-z0-9._-]{1,100})/videos/(\d{5,})/?$")
_FACEBOOK_VIDEO_PHP_PATH = re.compile(r"^/video\.php/?$")
_FACEBOOK_SHARE_PATH = re.compile(r"^/share/v/([A-Za-z0-9_-]{5,64})/?$")
_FACEBOOK_SHORT_PATH = re.compile(r"^/([A-Za-z0-9_-]{5,32})/?$")

_HOST_PLATFORMS = {
    "tiktok.com": "tiktok",
    "www.tiktok.com": "tiktok",
    "m.tiktok.com": "tiktok",
    "vt.tiktok.com": "tiktok",
    "vm.tiktok.com": "tiktok",
    "instagram.com": "instagram",
    "www.instagram.com": "instagram",
    "youtube.com": "youtube",
    "www.youtube.com": "youtube",
    "m.youtube.com": "youtube",
    "youtu.be": "youtube",
    "facebook.com": "facebook",
    "www.facebook.com": "facebook",
    "m.facebook.com": "facebook",
    "web.facebook.com": "facebook",
    "fb.watch": "facebook",
}

_CONTENT_TYPES = {
    "tiktok": frozenset({"public_video"}),
    "instagram": frozenset({"public_reel", "public_video_post"}),
    "youtube": frozenset({"public_video", "public_short"}),
    "facebook": frozenset({"public_video_post", "public_reel", "public_video"}),
}


@dataclass(frozen=True, slots=True)
class NormalizedURL:
    url: str
    platform: str
    content_type: str
    host: str
    source_id: str


def _invalid(message: str = "That URL is not valid.") -> UrlValidationError:
    return UrlValidationError(ErrorCode.INVALID_URL, message)


def _unsupported_platform() -> UrlValidationError:
    return UrlValidationError(
        ErrorCode.UNSUPPORTED_PLATFORM,
        "That platform is not supported. Send a TikTok, Instagram, YouTube or Facebook video link.",
    )


def _unsupported_content() -> UrlValidationError:
    return UrlValidationError(
        ErrorCode.UNSUPPORTED_CONTENT,
        "That link type is not supported. Send a public individual video link.",
    )


def _normalize_host(raw_host: str) -> str:
    try:
        ipaddress.ip_address(raw_host.split("%", 1)[0])
    except ValueError:
        pass
    else:
        raise UrlValidationError(ErrorCode.URL_BLOCKED, "That link destination is not allowed.")
    try:
        host = idna.encode(raw_host, uts46=True).decode("ascii").lower()
    except (idna.IDNAError, UnicodeError) as exc:
        raise _invalid() from exc
    if not host or host.endswith(".localhost") or host == "localhost":
        raise UrlValidationError(ErrorCode.URL_BLOCKED, "That link destination is not allowed.")
    return host


def _validate_path(path: str) -> str:
    if not path:
        return "/"
    if "%" in path or "\\" in path or "//" in path or ".." in path:
        raise _invalid()
    return path


def _single_query_value(query: str, key: str) -> str | None:
    values = parse_qs(query, keep_blank_values=True).get(key, [])
    if len(values) != 1 or not values[0]:
        return None
    return values[0]


def _normalize_tiktok(host: str, path: str) -> NormalizedURL:
    if host in {"vt.tiktok.com", "vm.tiktok.com"}:
        match = _TIKTOK_SHORT_PATH.match(path)
        if not match:
            raise _unsupported_content()
        code = match.group(1)
        return NormalizedURL(
            url=f"https://{host}/{code}",
            platform="tiktok",
            content_type="public_video",
            host=host,
            source_id=code,
        )

    match = _TIKTOK_VIDEO_PATH.match(path)
    if not match:
        raise _unsupported_content()
    username, video_id = match.groups()
    return NormalizedURL(
        url=f"https://www.tiktok.com/@{username}/video/{video_id}",
        platform="tiktok",
        content_type="public_video",
        host="www.tiktok.com",
        source_id=video_id,
    )


def _normalize_instagram(host: str, path: str) -> NormalizedURL:
    match = _INSTAGRAM_PATH.match(path)
    if not match:
        raise _unsupported_content()
    kind, shortcode = match.groups()
    content_type = "public_reel" if kind == "reel" else "public_video_post"
    return NormalizedURL(
        url=f"https://www.instagram.com/{kind}/{shortcode}/",
        platform="instagram",
        content_type=content_type,
        host="www.instagram.com",
        source_id=shortcode,
    )


def _normalize_youtube(host: str, path: str, query: str) -> NormalizedURL:
    if host == "youtu.be":
        match = _YOUTUBE_SHORT_PATH.match(path)
        if not match:
            raise _unsupported_content()
        video_id = match.group(1)
        return NormalizedURL(
            url=f"https://www.youtube.com/watch?v={video_id}",
            platform="youtube",
            content_type="public_video",
            host="www.youtube.com",
            source_id=video_id,
        )

    shorts_match = _YOUTUBE_SHORTS_PATH.match(path)
    if shorts_match:
        video_id = shorts_match.group(1)
        return NormalizedURL(
            url=f"https://www.youtube.com/shorts/{video_id}",
            platform="youtube",
            content_type="public_short",
            host="www.youtube.com",
            source_id=video_id,
        )

    if _YOUTUBE_WATCH_PATH.match(path):
        video_id = _single_query_value(query, "v")
        if video_id is None or not _YOUTUBE_VIDEO_ID.match(video_id):
            raise _unsupported_content()
        return NormalizedURL(
            url=f"https://www.youtube.com/watch?v={video_id}",
            platform="youtube",
            content_type="public_video",
            host="www.youtube.com",
            source_id=video_id,
        )

    raise _unsupported_content()


def _normalize_facebook(host: str, path: str, query: str) -> NormalizedURL:
    if host == "fb.watch":
        match = _FACEBOOK_SHORT_PATH.match(path)
        if not match:
            raise _unsupported_content()
        code = match.group(1)
        return NormalizedURL(
            url=f"https://fb.watch/{code}/",
            platform="facebook",
            content_type="public_video",
            host="fb.watch",
            source_id=code,
        )

    if _FACEBOOK_WATCH_PATH.match(path) or _FACEBOOK_VIDEO_PHP_PATH.match(path):
        video_id = _single_query_value(query, "v")
        if video_id is None or not video_id.isdigit() or len(video_id) < 5:
            raise _unsupported_content()
        return NormalizedURL(
            url=f"https://www.facebook.com/watch/?v={video_id}",
            platform="facebook",
            content_type="public_video",
            host="www.facebook.com",
            source_id=video_id,
        )

    reel_match = _FACEBOOK_REEL_PATH.match(path)
    if reel_match:
        reel_id = reel_match.group(1)
        return NormalizedURL(
            url=f"https://www.facebook.com/reel/{reel_id}/",
            platform="facebook",
            content_type="public_reel",
            host="www.facebook.com",
            source_id=reel_id,
        )

    share_match = _FACEBOOK_SHARE_PATH.match(path)
    if share_match:
        code = share_match.group(1)
        return NormalizedURL(
            url=f"https://www.facebook.com/share/v/{code}/",
            platform="facebook",
            content_type="public_video",
            host="www.facebook.com",
            source_id=code,
        )

    video_match = _FACEBOOK_VIDEO_PATH.match(path)
    if video_match:
        page, video_id = video_match.groups()
        return NormalizedURL(
            url=f"https://www.facebook.com/{page}/videos/{video_id}/",
            platform="facebook",
            content_type="public_video_post",
            host="www.facebook.com",
            source_id=video_id,
        )

    raise _unsupported_content()


def normalize_url(raw_url: str) -> NormalizedURL:
    if not raw_url or len(raw_url) > 2048:
        raise _invalid()

    try:
        parts = urlsplit(raw_url.strip())
        port = parts.port
    except ValueError as exc:
        raise _invalid() from exc

    scheme = parts.scheme.lower()
    if scheme not in {"http", "https"}:
        raise _invalid("Only http and https links are supported.")
    if parts.username is not None or parts.password is not None:
        raise UrlValidationError(
            ErrorCode.URL_BLOCKED, "Links containing credentials are not allowed."
        )

    default_port = 80 if scheme == "http" else 443
    if port is not None and port != default_port:
        raise UrlValidationError(ErrorCode.URL_BLOCKED, "That link uses an unsupported port.")
    if not parts.hostname:
        raise _invalid()

    host = _normalize_host(parts.hostname)
    platform = _HOST_PLATFORMS.get(host)
    if platform is None:
        raise _unsupported_platform()

    path = _validate_path(parts.path)
    if platform == "tiktok":
        normalized = _normalize_tiktok(host, path)
    elif platform == "instagram":
        normalized = _normalize_instagram(host, path)
    elif platform == "youtube":
        normalized = _normalize_youtube(host, path, parts.query)
    else:
        normalized = _normalize_facebook(host, path, parts.query)

    if normalized.content_type not in _CONTENT_TYPES[normalized.platform]:
        raise _unsupported_content()
    return normalized


def _is_global_address(raw_address: str) -> bool:
    try:
        address = ipaddress.ip_address(raw_address.split("%", 1)[0])
    except ValueError:
        return False
    return address.is_global


async def resolve_public_addresses(host: str) -> tuple[str, ...]:
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise UrlValidationError(
            ErrorCode.SOURCE_UNAVAILABLE, "That link could not be reached. Try again later."
        ) from exc

    addresses = tuple({str(info[4][0]) for info in infos})
    if not addresses:
        raise UrlValidationError(ErrorCode.URL_BLOCKED, "That link destination is not allowed.")
    if any(not _is_global_address(address) for address in addresses):
        raise UrlValidationError(ErrorCode.URL_BLOCKED, "That link destination is not allowed.")
    return addresses
