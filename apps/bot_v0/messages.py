"""User-facing copy for the v0 bot, rendered as Telegram HTML."""

from __future__ import annotations

from html import escape

from apps.bot_v0.branding import BRAND_NAME, BRAND_TAGLINE
from backend.delivery.presentation import build_caption
from backend.downloads.engine import PreparedDownload


def _handle(username: str | None) -> str:
    return f"@{username}" if username else BRAND_NAME


def _human_bytes(value: int) -> str:
    amount = float(value)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if amount < 1024 or unit == "GiB":
            return f"{amount:.0f} {unit}" if unit == "B" else f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{amount:.1f} GiB"


def _human_duration(seconds: int) -> str:
    minutes, remainder = divmod(int(seconds), 60)
    if minutes < 60:
        return f"{minutes}m {remainder}s" if minutes else f"{remainder}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m"


def progress_bar(used: int, limit: int, *, width: int = 5) -> str:
    if limit <= 0:
        return ""
    filled = round(width * min(max(used, 0), limit) / limit)
    return "▰" * filled + "▱" * (width - filled)


def start_caption(username: str | None = None) -> str:
    return (
        f"<b>{escape(BRAND_NAME)}</b>\n"
        f"{escape(BRAND_TAGLINE)}\n\n"
        "Send a public TikTok, Instagram, YouTube or Facebook link and I will send the "
        "video back here.\n\n"
        f"<i>Public content only · {escape(_handle(username))}</i>"
    )


def help_card(username: str | None = None) -> str:
    return (
        "<b>How it works</b>\n"
        "1. Copy a public video link.\n"
        "2. Send it here as a message.\n"
        "3. Wait for the video.\n\n"
        "<b>Good to know</b>\n"
        "· One download runs at a time.\n"
        "· Failed downloads do not use your allowance.\n"
        "· Playlists, live streams and private content are rejected.\n"
        "· The daily allowance resets at midnight Africa/Lagos.\n\n"
        f"<i>{escape(_handle(username))}</i>"
    )


def platforms_card() -> str:
    return (
        "<b>Supported links</b>\n"
        "<b>TikTok</b> · tiktok.com/@user/video/123\n"
        "<b>Instagram</b> · instagram.com/reel/ABC\n"
        "<b>YouTube</b> · youtube.com/watch?v=... or youtube.com/shorts/...\n"
        "<b>Facebook</b> · facebook.com/.../videos/... or facebook.com/reel/...\n\n"
        "<i>Individual public videos only. No playlists, channels or live streams.</i>"
    )


def status_card(
    *,
    used: int,
    limit: int,
    max_height: int,
    max_bytes: int,
    max_duration_seconds: int,
) -> str:
    remaining = max(0, limit - used)
    return (
        "<b>Your status</b>\n"
        "Plan: Free\n"
        f"Today: {used} of {limit} used ({remaining} left)\n"
        f"<code>{progress_bar(used, limit)}</code>\n\n"
        f"Quality: up to {max_height}p\n"
        f"Duration: up to {_human_duration(max_duration_seconds)}\n"
        f"Size: up to {_human_bytes(max_bytes)}\n\n"
        "<i>Usage is kept in memory for this bot process and resets on restart.</i>"
    )


def accepted_text() -> str:
    return "<b>Working on it</b>\nReading the link..."


_STAGE_LABELS = {
    "inspecting": "Checking the video...",
    "downloading": "Downloading the video...",
    "preparing": "Getting it ready for Telegram...",
}


def stage_text(stage: str) -> str:
    return f"<b>Working on it</b>\n{_STAGE_LABELS.get(stage, 'Processing...')}"


def done_text() -> str:
    return "<b>Delivered</b>\nSend another public link whenever you are ready."


def rejection_text(safe_message: str) -> str:
    return f"<b>Could not download that</b>\n{escape(safe_message)}"


def quota_exhausted_text(limit: int) -> str:
    return (
        "<b>Daily limit reached</b>\n"
        f"You have used all {limit} downloads for today. "
        "The allowance resets at midnight Africa/Lagos."
    )


def busy_text() -> str:
    return (
        "<b>One at a time</b>\n"
        "Your current download is still running. Send the next link when it finishes."
    )


def not_a_link_text() -> str:
    return (
        "<b>Send a video link</b>\n"
        "Paste a public TikTok, Instagram, YouTube or Facebook link, for example:\n"
        "<code>https://www.youtube.com/watch?v=dQw4w9WgXcQ</code>"
    )


def private_beta_text() -> str:
    return (
        "<b>Private beta</b>\n"
        "This bot is limited to approved accounts. Ask the operator to add your Telegram ID."
    )


def timeout_text() -> str:
    return "<b>Timed out</b>\nThat download took too long and was stopped. Try a shorter video."


def unexpected_error_text() -> str:
    return "<b>Something went wrong</b>\nPlease try again later."


def success_caption(prepared: PreparedDownload) -> str:
    return build_caption(
        platform=prepared.normalized.platform,
        title=prepared.metadata.title,
        uploader=prepared.metadata.uploader,
        height=prepared.media.probe.quality_height,
    )
