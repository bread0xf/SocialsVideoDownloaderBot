"""Brand identity for the v0 bot. Change these values to rebrand it."""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path

BRAND_NAME = "SV Downloader"
BRAND_TAGLINE = "Public videos, straight to Telegram."

SHORT_DESCRIPTION = "Save public TikTok, Instagram, YouTube and Facebook videos to Telegram."
DESCRIPTION = (
    "Send a public video link from TikTok, Instagram, YouTube or Facebook "
    "and get the video back in this chat.\n\n"
    "Public content only. No logins, cookies or private content."
)
COMMANDS: tuple[tuple[str, str], ...] = (
    ("start", "Start the bot"),
    ("help", "How it works"),
    ("status", "Usage and limits"),
)

LOGO_RESOURCE = ("assets", "logo.png")


def logo_path() -> Path:
    resource = files("apps.bot_v0")
    for part in LOGO_RESOURCE:
        resource = resource.joinpath(part)
    return Path(str(resource))
