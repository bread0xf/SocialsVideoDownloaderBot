from __future__ import annotations

import structlog
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from apps.bot_v0.handlers import (
    card_callback,
    handle_message,
    help_command,
    start,
    status_command,
)
from apps.bot_v0.state import BotV0Config, BotV0State
from backend.core.config import Settings, get_settings
from backend.core.logging import configure_logging
from backend.delivery.telegram import BotDelivery
from backend.downloads.engine import EngineLimits, InProcessEngine

logger = structlog.get_logger(__name__)


def build_state(settings: Settings) -> BotV0State:
    limits = EngineLimits.free_plan(settings)
    return BotV0State(
        BotV0Config(
            daily_limit=settings.v0_effective_daily_limit,
            max_height=limits.max_height,
            max_bytes=limits.max_bytes,
            max_duration_seconds=limits.max_duration_seconds,
            job_timeout_seconds=settings.job_timeout_seconds,
            media_root=settings.v0_media_root,
            allowed_user_ids=settings.v0_allowed_user_id_set,
            max_active_jobs_per_user=settings.v0_max_active_jobs_per_user,
        )
    )


def build_application(
    settings: Settings,
    *,
    state: BotV0State | None = None,
    engine: InProcessEngine | None = None,
) -> Application:
    token = settings.telegram_v0_token
    if not token:
        raise SystemExit(
            "TELEGRAM_V0_BOT_TOKEN (or TELEGRAM_BOT_TOKEN) is not configured. "
            "Set it in .env and retry."
        )

    application = (
        Application.builder()
        .token(token)
        .concurrent_updates(max(4, settings.worker_concurrency))
        .build()
    )
    application.bot_data["v0_state"] = state or build_state(settings)
    application.bot_data["engine"] = engine or InProcessEngine(EngineLimits.free_plan(settings))
    application.bot_data["delivery"] = BotDelivery(application.bot)

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(
        CallbackQueryHandler(card_callback, pattern="^(start|help|status|platforms)$")
    )
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    return application


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)

    if not settings.telegram_v0_token:
        raise SystemExit(
            "TELEGRAM_V0_BOT_TOKEN (or TELEGRAM_BOT_TOKEN) is not configured. "
            "Set it in .env and retry."
        )
    if settings.app_env == "production":
        logger.warning(
            "v0_bot_production_environment",
            detail="v0 keeps usage in memory and is not a production ledger",
        )

    state = build_state(settings)
    logger.info(
        "v0_bot_starting",
        daily_limit=state.config.daily_limit,
        max_height=state.config.max_height,
        max_duration_seconds=state.config.max_duration_seconds,
        allow_listed=len(state.config.allowed_user_ids),
    )
    application = build_application(settings, state=state)
    application.run_polling(allowed_updates=["message"], drop_pending_updates=True)
