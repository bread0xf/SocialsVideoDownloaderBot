from dataclasses import dataclass
from typing import Protocol

from telegram import Bot, InputFile
from telegram.error import TelegramError

from backend.media.processing import PreparedMedia


@dataclass(frozen=True, slots=True)
class DeliveredMedia:
    message_id: int
    file_id: str | None


class Delivery(Protocol):
    async def send_video(
        self,
        chat_id: int,
        media: PreparedMedia,
        *,
        caption: str | None = None,
        parse_mode: str | None = None,
    ) -> DeliveredMedia: ...

    async def send_text(self, chat_id: int, text: str) -> None: ...


class BotDelivery:
    def __init__(self, bot: Bot) -> None:
        self._bot = bot

    async def send_video(
        self,
        chat_id: int,
        media: PreparedMedia,
        *,
        caption: str | None = None,
        parse_mode: str | None = None,
    ) -> DeliveredMedia:
        duration = int(media.probe.duration_seconds) if media.probe.duration_seconds else None
        try:
            message = await self._bot.send_video(
                chat_id=chat_id,
                video=InputFile(str(media.path), filename="video.mp4"),
                caption=caption,
                parse_mode=parse_mode,
                supports_streaming=True,
                width=media.probe.width,
                height=media.probe.height,
                duration=duration,
                read_timeout=120,
                write_timeout=120,
            )
        except TelegramError as exc:
            raise TelegramDeliveryError from exc
        file_id = message.video.file_id if message.video is not None else None
        return DeliveredMedia(message_id=message.message_id, file_id=file_id)

    async def send_text(self, chat_id: int, text: str) -> None:
        try:
            await self._bot.send_message(chat_id=chat_id, text=text)
        except TelegramError:
            return


class TelegramDeliveryError(Exception):
    pass
