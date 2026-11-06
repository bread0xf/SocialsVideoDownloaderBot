from collections.abc import Callable, Coroutine
from datetime import UTC
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from backend.core.config import Settings, get_settings
from backend.core.errors import AppError
from backend.core.logging import configure_logging
from backend.database.session import build_engine, build_session_factory, session_scope
from backend.downloads.service import submit_download
from backend.entitlements.service import resolve_entitlement
from backend.platforms.urls import normalize_url
from backend.usage.service import included_usage
from backend.users.service import TelegramIdentity, upsert_telegram_user

logger = structlog.get_logger(__name__)

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
    "Use /status to see your plan and remaining daily downloads.\n"
    "Free plan: up to 5 successful downloads per Africa/Lagos day, up to 480p.\n"
    "Unsupported or private links are rejected."
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message is not None:
        await update.effective_message.reply_text(START_TEXT)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message is not None:
        await update.effective_message.reply_text(HELP_TEXT)


def _identity(update: Update) -> TelegramIdentity | None:
    telegram_user = update.effective_user
    if telegram_user is None:
        return None
    return TelegramIdentity(
        telegram_user_id=telegram_user.id,
        username=telegram_user.username,
        first_name=telegram_user.first_name,
        last_name=telegram_user.last_name,
        language_code=telegram_user.language_code,
    )


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    identity = _identity(update)
    session_factory = context.application.bot_data.get("session_factory")
    if message is None or identity is None or session_factory is None:
        return

    async with session_scope(session_factory) as session:
        user = await upsert_telegram_user(session, identity)
        entitlement = await resolve_entitlement(session, user.id)
        used = await included_usage(session, user.id, entitlement)

    plan_name = "Premium" if entitlement.is_premium else "Free"
    if entitlement.daily_included_limit is None:
        allowance = "Daily allowance is not configured yet."
    else:
        remaining = max(0, entitlement.daily_included_limit - used)
        allowance = (
            f"Today: {used}/{entitlement.daily_included_limit} used ({remaining} remaining)."
        )
    lines = [
        f"Plan: {plan_name}",
        allowance,
        f"Maximum quality: {entitlement.max_resolution_p}p",
    ]
    if entitlement.paid_through is not None:
        paid_through = entitlement.paid_through.astimezone(UTC)
        lines.append("Active through: " + paid_through.strftime("%Y-%m-%d %H:%M UTC"))
    await message.reply_text("\n".join(lines))


async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    identity = _identity(update)
    if message is None or identity is None or not message.text:
        return

    try:
        normalized = normalize_url(message.text)
    except AppError as exc:
        await message.reply_text(exc.safe_message)
        return

    session_factory = context.application.bot_data.get("session_factory")
    if session_factory is None:
        await message.reply_text("The service is temporarily unavailable. Try again later.")
        return

    idempotency_key = f"telegram:{update.update_id}"

    try:
        async with session_scope(session_factory) as session:
            user = await upsert_telegram_user(session, identity)
            result = await submit_download(
                session,
                user=user,
                normalized_url=normalized,
                idempotency_key=idempotency_key,
            )
    except AppError as exc:
        await message.reply_text(exc.safe_message)
        return
    except Exception:
        logger.exception("download_submission_failed", platform=normalized.platform)
        await message.reply_text("Something went wrong. Please try again later.")
        return

    if result.created:
        await message.reply_text("Added to the queue. I will send the video here when it is ready.")


def build_application(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    post_shutdown: Callable[[Application], Coroutine[Any, Any, None]] | None = None,
) -> Application:
    builder = Application.builder().token(settings.telegram_token)
    if post_shutdown is not None:
        builder = builder.post_shutdown(post_shutdown)
    application = builder.build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))
    if session_factory is not None:
        application.bot_data["session_factory"] = session_factory
    return application


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)

    if not settings.telegram_token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not configured. Set it in .env and retry.")

    engine = build_engine(settings)
    session_factory = build_session_factory(engine)

    async def dispose_engine(_: Application) -> None:
        await engine.dispose()

    application = build_application(settings, session_factory, dispose_engine)
    application.run_polling()
