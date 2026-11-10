"""User-facing caption and filename for a delivered video."""

from __future__ import annotations

import re
from html import escape

_PLATFORM_NAMES = {
    "tiktok": "TikTok",
    "instagram": "Instagram",
    "youtube": "YouTube",
    "facebook": "Facebook",
}

_UNSAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")
_CAPTION_LIMIT = 1024


def platform_name(platform: str) -> str:
    return _PLATFORM_NAMES.get(platform, platform.replace("_", " ").title())


def build_filename(platform: str, source_id: str) -> str:
    safe_id = _UNSAFE_FILENAME.sub("-", source_id).strip("-._") or "video"
    return f"{platform_name(platform).lower()}-{safe_id}.mp4"


def build_caption(
    *,
    platform: str,
    title: str | None = None,
    uploader: str | None = None,
    height: int | None = None,
) -> str:
    lines: list[str] = []
    clean_title = " ".join(title.split())[:200].rstrip() if title else ""
    if clean_title:
        lines.append(f"<b>{escape(clean_title)}</b>")
    clean_uploader = " ".join(uploader.split())[:100].rstrip() if uploader else ""
    if clean_uploader:
        lines.append(f"<i>by {escape(clean_uploader)}</i>")
    footer = platform_name(platform)
    if height:
        footer = f"{footer} · {height}p"
    lines.append(footer)
    return "\n".join(lines)[:_CAPTION_LIMIT]
