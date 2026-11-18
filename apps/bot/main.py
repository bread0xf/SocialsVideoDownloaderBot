import uuid
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from backend.ads import AdOffer, AdProvider, AdProviderError
from backend.ads.adsun import build_adsun_provider
from backend.core.config import Settings, get_settings
from backend.core.errors import AppError, ErrorCode
from backend.core.logging import configure_logging
from backend.database.session import build_engine, build_session_factory, session_scope
from backend.downloads.service import submit_download
from backend.entitlements.service import Entitlement, resolve_entitlement
from backend.platforms.urls import normalize_url, resolve_public_addresses
from backend.rewards.policy import REWARD_PROVIDER
from backend.rewards.service import expire_reward_session, open_reward_ad_session
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

REWARD_CALLBACK = "reward:show"
REWARD_BUTTON_TEXT = "Watch an ad for +1 download"
REWARD_DISABLED_TEXT = "Rewarded downloads are not available right now."
REWARD_NO_AD_TEXT = "No ad is available right now. Please try again later."
REWARD_ERROR_TEXT = "The ad service is temporarily unavailable. Please try again later."
REWARD_PENDING_TEXT = (
    "Watch the ad to earn an extra download. The download is added after the ad "
    "network confirms completion."
)
REWARD_SESSION_PENDING_TEXT = (
    "You already have an ad in progress. Finish that ad first; then you can request another one."
)
REWARD_BLOCKED_TEXT = "Rewarded downloads are not available for this account."
REWARD_PREMIUM_TEXT = "Rewarded downloads are not available on your current plan."
REWARD_CAP_TEXT = "Daily reward limit reached. It resets at midnight Africa/Lagos."


def _reward_cap_text(resets_at: datetime | None) -> str:
    if resets_at is None:
        return REWARD_CAP_TEXT
    return (
        f"Daily reward limit reached. It resets at midnight Africa/Lagos ({resets_at:%H:%M} UTC)."
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


def reward_markup_for(entitlement: Entitlement) -> InlineKeyboardMarkup | None:
    """Offer the rewarded ad only to plans that may see sponsor placements."""
    if not entitlement.sponsor_eligible:
        return None
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(REWARD_BUTTON_TEXT, callback_data=REWARD_CALLBACK)]]
    )


def _ad_markup(offer: AdOffer) -> InlineKeyboardMarkup | None:
    rows = [[InlineKeyboardButton(label, url=url) for label, url in row] for row in offer.buttons()]
    return InlineKeyboardMarkup(rows) if rows else None


async def _reward_keyboard(
    context: ContextTypes.DEFAULT_TYPE, identity: TelegramIdentity
) -> InlineKeyboardMarkup | None:
    """Return the reward button for an eligible user, or ``None``.

    Any failure here is swallowed by the caller so the download flow is never
    broken by the ad feature.
    """
    settings = context.application.bot_data.get("settings")
    session_factory = context.application.bot_data.get("session_factory")
    if settings is None or session_factory is None or not settings.adsun_enabled:
        return None
    if context.application.bot_data.get("ad_provider") is None:
        return None

    async with session_scope(session_factory) as session:
        user = await upsert_telegram_user(session, identity)
        entitlement = await resolve_entitlement(session, user.id)
    return reward_markup_for(entitlement)


async def _close_reward_session(
    session_factory: async_sessionmaker[AsyncSession],
    session_id: uuid.UUID,
    *,
    reason: str,
) -> None:
    """Expire a session when the ad could not be served, so the user can retry."""
    try:
        async with session_scope(session_factory) as session:
            await expire_reward_session(
                session,
                session_id=session_id,
                now=datetime.now(UTC),
                reason=reason,
            )
    except Exception as exc:
        logger.error(
            "reward_session_expire_failed",
            provider=REWARD_PROVIDER,
            reason=reason,
            error_type=type(exc).__name__,
        )


async def _send_reward_ad(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    identity = _identity(update)
    if message is None or identity is None:
        return

    settings = context.application.bot_data.get("settings")
    provider = context.application.bot_data.get("ad_provider")
    session_factory = context.application.bot_data.get("session_factory")
    if (
        settings is None
        or provider is None
        or not settings.adsun_enabled
        or not settings.adsun_block_id
    ):
        await message.reply_text(REWARD_DISABLED_TEXT)
        return
    if session_factory is None:
        logger.warning("reward_session_store_unavailable", provider=REWARD_PROVIDER)
        await message.reply_text(REWARD_ERROR_TEXT)
        return

    now = datetime.now(UTC)
    ad_session = None
    try:
        async with session_scope(session_factory) as session:
            user = await upsert_telegram_user(session, identity)
            ad_session = await open_reward_ad_session(
                session,
                user=user,
                provider=REWARD_PROVIDER,
                block=settings.adsun_block_id,
                now=now,
                settings=settings,
            )
    except Exception as exc:
        logger.error(
            "reward_session_open_failed",
            provider=REWARD_PROVIDER,
            error_type=type(exc).__name__,
        )
        await message.reply_text(REWARD_ERROR_TEXT)
        return

    if ad_session is None:
        await message.reply_text(REWARD_ERROR_TEXT)
        return
    if ad_session.status == "reused":
        # The pending session is the ad cooldown: do not fetch a second ad.
        await message.reply_text(REWARD_SESSION_PENDING_TEXT)
        return
    if ad_session.status == "capped":
        await message.reply_text(_reward_cap_text(ad_session.cap_resets_at))
        return
    if ad_session.status == "premium_ineligible":
        await message.reply_text(REWARD_PREMIUM_TEXT)
        return
    if ad_session.status == "blocked":
        await message.reply_text(REWARD_BLOCKED_TEXT)
        return

    session_id = ad_session.session_id
    if session_id is None:
        logger.error("reward_session_missing_after_open", provider=REWARD_PROVIDER)
        await message.reply_text(REWARD_ERROR_TEXT)
        return

    try:
        offer = await provider.fetch_ad(
            telegram_user_id=identity.telegram_user_id,
            language=identity.language_code or "",
        )
    except AdProviderError as exc:
        logger.warning(
            "ad_request_failed",
            provider="adsun",
            reason=exc.reason,
            status=exc.status,
        )
        await _close_reward_session(session_factory, session_id, reason="provider_error")
        await message.reply_text(REWARD_ERROR_TEXT)
        return
    except Exception:
        # Do not attach exception details: they can contain request internals.
        logger.warning("ad_request_failed", provider="adsun", reason="unexpected")
        await _close_reward_session(session_factory, session_id, reason="unexpected_error")
        await message.reply_text(REWARD_ERROR_TEXT)
        return

    if offer is None:
        await _close_reward_session(session_factory, session_id, reason="no_fill")
        await message.reply_text(REWARD_NO_AD_TEXT)
        return

    try:
        markup = _ad_markup(offer)
        if offer.image_url:
            await message.reply_photo(
                photo=offer.image_url,
                caption=offer.text_html,
                parse_mode=ParseMode.HTML,
                protect_content=True,
                reply_markup=markup,
            )
        else:
            await message.reply_text(
                offer.text_html,
                parse_mode=ParseMode.HTML,
                protect_content=True,
                reply_markup=markup,
            )
    except Exception:
        logger.warning("ad_delivery_failed", provider="adsun")
        await _close_reward_session(session_factory, session_id, reason="delivery_failed")
        await message.reply_text(REWARD_ERROR_TEXT)
        return

    await message.reply_text(REWARD_PENDING_TEXT)


async def reward_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_reward_ad(update, context)


async def reward_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is not None:
        try:
            await query.answer()
        except Exception:
            logger.warning("reward_callback_answer_failed")
    await _send_reward_ad(update, context)


async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    identity = _identity(update)
    if message is None or identity is None or not message.text:
        return

    try:
        normalized = normalize_url(message.text)
        await resolve_public_addresses(normalized.host)
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
        reply_markup: InlineKeyboardMarkup | None = None
        if exc.code == ErrorCode.QUOTA_EXHAUSTED:
            try:
                reply_markup = await _reward_keyboard(context, identity)
            except Exception:
                logger.exception("reward_button_failed")
                reply_markup = None
        await message.reply_text(exc.safe_message, reply_markup=reply_markup)
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
    ad_provider: AdProvider | None = None,
) -> Application:
    builder = Application.builder().token(settings.telegram_token)
    if post_shutdown is not None:
        builder = builder.post_shutdown(post_shutdown)
    application = builder.build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("reward", reward_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))
    application.add_handler(CallbackQueryHandler(reward_callback, pattern=f"^{REWARD_CALLBACK}$"))
    application.bot_data["settings"] = settings
    if session_factory is not None:
        application.bot_data["session_factory"] = session_factory
    if ad_provider is not None:
        application.bot_data["ad_provider"] = ad_provider
    return application


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)

    if not settings.telegram_token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not configured. Set it in .env and retry.")

    engine = build_engine(settings)
    session_factory = build_session_factory(engine)

    ad_provider = build_adsun_provider(settings)

    async def dispose_engine(_: Application) -> None:
        await engine.dispose()

    application = build_application(settings, session_factory, dispose_engine, ad_provider)
    application.run_polling()
