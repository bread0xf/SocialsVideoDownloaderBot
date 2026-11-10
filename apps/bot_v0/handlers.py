from __future__ import annotations

import asyncio
from typing import cast
from urllib.parse import urlsplit

import structlog
from telegram import CallbackQuery, InlineKeyboardMarkup, InputFile, Message, Update
from telegram.constants import ChatAction
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from apps.bot_v0 import branding, keyboards, messages
from apps.bot_v0.state import BotV0State
from backend.core.errors import AppError, ErrorCode
from backend.delivery.presentation import build_caption, build_filename
from backend.delivery.telegram import Delivery, TelegramDeliveryError
from backend.downloads.engine import InProcessEngine, PreparedDownload

logger = structlog.get_logger(__name__)


def _state(context: ContextTypes.DEFAULT_TYPE) -> BotV0State:
    return cast(BotV0State, context.application.bot_data["v0_state"])


def _engine(context: ContextTypes.DEFAULT_TYPE) -> InProcessEngine:
    return cast(InProcessEngine, context.application.bot_data["engine"])


def _looks_like_url(text: str) -> bool:
    parts = urlsplit(text)
    return parts.scheme.lower() in {"http", "https"} and bool(parts.netloc)


def _status_text(state: BotV0State, user_id: int) -> str:
    config = state.config
    return messages.status_card(
        used=state.usage.used(user_id),
        limit=config.daily_limit,
        max_height=config.max_height,
        max_bytes=config.max_bytes,
        max_duration_seconds=config.max_duration_seconds,
    )


async def _deny(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return True
    if not _state(context).is_allowed(user.id):
        await message.reply_text(messages.private_beta_text(), parse_mode="HTML")
        return True
    return False


async def _edit(
    message: Message,
    text: str,
    keyboard: InlineKeyboardMarkup | None = None,
) -> None:
    try:
        await message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=keyboard,
            disable_web_page_preview=True,
        )
    except TelegramError:
        logger.debug("v0_ack_edit_failed")


async def _edit_card(
    query: CallbackQuery,
    text: str,
    keyboard: InlineKeyboardMarkup,
) -> None:
    message = query.message
    try:
        if message is not None and getattr(message, "photo", None):
            await query.edit_message_caption(
                caption=text,
                parse_mode="HTML",
                reply_markup=keyboard,
            )
        else:
            await query.edit_message_text(
                text=text,
                parse_mode="HTML",
                reply_markup=keyboard,
                disable_web_page_preview=True,
            )
    except TelegramError:
        logger.debug("v0_card_edit_failed")


async def _deliver(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    prepared: PreparedDownload,
) -> None:
    bot = context.bot
    try:
        await bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_VIDEO)
    except TelegramError:
        pass
    delivery = cast(Delivery, context.application.bot_data["delivery"])
    try:
        await delivery.send_video(
            chat_id,
            prepared.media,
            caption=build_caption(
                platform=prepared.normalized.platform,
                title=prepared.metadata.title,
                uploader=prepared.metadata.uploader,
                height=prepared.media.probe.quality_height,
            ),
            parse_mode="HTML",
            filename=build_filename(
                prepared.normalized.platform,
                prepared.normalized.source_id,
            ),
        )
    except TelegramDeliveryError as exc:
        raise AppError(
            ErrorCode.TELEGRAM_DELIVERY_FAILED,
            "The video could not be delivered to Telegram. Please try again later.",
        ) from exc


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _deny(update, context):
        return
    message = update.effective_message
    if message is None:
        return
    caption = messages.start_caption(context.bot.username)
    keyboard = keyboards.start_keyboard()
    try:
        await message.reply_photo(
            photo=InputFile(branding.logo_path().read_bytes(), filename="logo.png"),
            caption=caption,
            parse_mode="HTML",
            reply_markup=keyboard,
        )
    except TelegramError:
        logger.warning("v0_logo_send_failed")
        await message.reply_text(
            caption,
            parse_mode="HTML",
            reply_markup=keyboard,
            disable_web_page_preview=True,
        )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _deny(update, context):
        return
    message = update.effective_message
    if message is not None:
        await message.reply_text(
            messages.help_card(context.bot.username),
            parse_mode="HTML",
            reply_markup=keyboards.card_keyboard(),
            disable_web_page_preview=True,
        )


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _deny(update, context):
        return
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return
    await message.reply_text(
        _status_text(_state(context), user.id),
        parse_mode="HTML",
        reply_markup=keyboards.status_keyboard(),
    )


async def card_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return
    user = update.effective_user
    state = _state(context)
    if user is None or not state.is_allowed(user.id):
        await query.answer(messages.private_beta_text(), show_alert=True)
        return
    await query.answer()

    username = context.bot.username
    data = query.data or "start"
    if data == "help":
        text, keyboard = messages.help_card(username), keyboards.card_keyboard()
    elif data == "platforms":
        text, keyboard = messages.platforms_card(), keyboards.card_keyboard()
    elif data == "status":
        text, keyboard = _status_text(state, user.id), keyboards.status_keyboard()
    else:
        text, keyboard = messages.start_caption(username), keyboards.start_keyboard()
    await _edit_card(query, text, keyboard)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None or not message.text:
        return
    state = _state(context)
    if not state.is_allowed(user.id):
        await message.reply_text(messages.private_beta_text(), parse_mode="HTML")
        return
    if state.recent_updates.seen(update.update_id):
        return

    raw_url = message.text.strip()
    if not _looks_like_url(raw_url):
        await message.reply_text(
            messages.not_a_link_text(),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        return
    if state.usage.remaining(user.id) <= 0:
        await message.reply_text(
            messages.quota_exhausted_text(state.config.daily_limit),
            parse_mode="HTML",
        )
        return
    if not await state.jobs.acquire(user.id):
        await message.reply_text(messages.busy_text(), parse_mode="HTML")
        return

    ack = await message.reply_text(messages.accepted_text(), parse_mode="HTML")

    async def on_stage(stage: str) -> None:
        await _edit(ack, messages.stage_text(stage))

    try:
        async with asyncio.timeout(state.config.job_timeout_seconds):
            async with _engine(context).prepare(
                raw_url,
                state.config.media_root,
                on_stage=on_stage,
            ) as prepared:
                logger.info("v0_download_started", platform=prepared.normalized.platform)
                await _deliver(context, message.chat_id, prepared)
                logger.info("v0_download_delivered", platform=prepared.normalized.platform)
        state.usage.record(user.id)
        await _edit(ack, messages.done_text(), keyboards.done_keyboard())
    except TimeoutError:
        logger.info("v0_download_timeout")
        await _edit(ack, messages.timeout_text())
    except AppError as exc:
        logger.info("v0_download_rejected", error_code=exc.code.value)
        await _edit(ack, messages.rejection_text(exc.safe_message))
    except Exception:
        logger.exception("v0_download_failed")
        await _edit(ack, messages.unexpected_error_text())
    finally:
        await state.jobs.release(user.id)
