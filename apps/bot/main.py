from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from backend.core.config import Settings, get_settings
from backend.core.logging import configure_logging

START_TEXT = (
    "Send me a public video link from TikTok, Instagram, YouTube or Facebook "
    "and I will try to deliver it here.\n\n"
    "I only handle publicly accessible content. I do not accept logins, cookies "
    "or private/restricted links."
)

HELP_TEXT = (
    "How to use:\n"
    "1. Copy a public video link.\n"
    "2. Send it here as a message.\n"
    "3. Wait for the bot to process and deliver the media.\n\n"
    "Free plan: up to 5 successful downloads per Africa/Lagos day, up to 480p.\n"
    "Unsupported or private links are rejected."
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message is not None:
        await update.effective_message.reply_text(START_TEXT)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message is not None:
        await update.effective_message.reply_text(HELP_TEXT)


def build_application(settings: Settings) -> Application:
    application = Application.builder().token(settings.telegram_token).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    return application


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)

    if not settings.telegram_token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not configured. Set it in .env and retry.")

    application = build_application(settings)
    application.run_polling()
