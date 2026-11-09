"""Apply the v0 bot profile: name, descriptions, commands and logo."""

from __future__ import annotations

import asyncio

import structlog
from telegram import Bot, InputProfilePhotoStatic

from apps.bot_v0 import branding
from backend.core.config import get_settings
from backend.core.logging import configure_logging

logger = structlog.get_logger(__name__)


async def configure_profile(bot: Bot) -> None:
    await bot.set_my_name(name=branding.BRAND_NAME)
    await bot.set_my_short_description(short_description=branding.SHORT_DESCRIPTION)
    await bot.set_my_description(description=branding.DESCRIPTION)
    await bot.set_my_commands(commands=list(branding.COMMANDS))
    with branding.logo_path().open("rb") as photo:
        await bot.set_my_profile_photo(
            photo=InputProfilePhotoStatic(photo),
            read_timeout=60,
            write_timeout=60,
            connect_timeout=20,
        )


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    token = settings.telegram_v0_token
    if not token:
        raise SystemExit(
            "TELEGRAM_V0_BOT_TOKEN (or TELEGRAM_BOT_TOKEN) is not configured. "
            "Set it in .env and retry."
        )

    async def _run() -> None:
        bot = Bot(token)
        await bot.initialize()
        try:
            await configure_profile(bot)
        finally:
            await bot.shutdown()

    asyncio.run(_run())
    logger.info("v0_profile_configured", brand=branding.BRAND_NAME)


if __name__ == "__main__":
    main()
