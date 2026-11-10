from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from apps.bot_v0 import branding, messages
from apps.bot_v0.handlers import card_callback, handle_message, start, status_command
from apps.bot_v0.state import BotV0Config, BotV0State
from backend.core.errors import AppError, ErrorCode
from backend.delivery.telegram import DeliveredMedia, TelegramDeliveryError
from backend.downloads.engine import PreparedDownload
from backend.media.ffprobe import ProbeResult
from backend.media.processing import PreparedMedia
from backend.platforms.adapters.base import FormatSelection, MediaMetadata
from backend.platforms.urls import NormalizedURL

URL = "https://youtu.be/dQw4w9WgXcQ"


class _Ack:
    def __init__(self, edits: list[tuple[str, dict[str, Any]]]) -> None:
        self._edits = edits

    async def edit_text(self, text: str, **kwargs: Any) -> None:
        self._edits.append((text, kwargs))


class _FakeMessage:
    def __init__(self, text: str = "") -> None:
        self.text = text
        self.chat_id = 42
        self.replies: list[tuple[str, dict[str, Any]]] = []
        self.edits: list[tuple[str, dict[str, Any]]] = []
        self.photos: list[tuple[str | None, dict[str, Any]]] = []

    async def reply_text(self, text: str, **kwargs: Any) -> _Ack:
        self.replies.append((text, kwargs))
        return _Ack(self.edits)

    async def reply_photo(
        self,
        photo: Any = None,
        caption: str | None = None,
        **kwargs: Any,
    ) -> _Ack:
        self.photos.append((caption, kwargs))
        return _Ack(self.edits)


class _FakeBot:
    username = "sv_test_bot"

    def __init__(self) -> None:
        self.actions: list[tuple[int, str]] = []

    async def send_chat_action(self, chat_id: int, action: str) -> None:
        self.actions.append((chat_id, action))


class _FakeEngine:
    def __init__(
        self,
        *,
        prepared: PreparedDownload | None = None,
        error: AppError | None = None,
        stages: list[str] | None = None,
    ) -> None:
        self.prepared = prepared
        self.error = error
        self.stages = stages or []
        self.calls: list[str] = []

    @asynccontextmanager
    async def prepare(
        self,
        raw_url: str,
        workspace_root: Path,
        *,
        on_stage: Any = None,
    ) -> Any:
        self.calls.append(raw_url)
        if self.error is not None:
            raise self.error
        if on_stage is not None:
            for stage in self.stages:
                await on_stage(stage)
        assert self.prepared is not None
        yield self.prepared


class _FakeDelivery:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple[int, PreparedMedia, str | None, str | None, str | None]] = []

    async def send_video(
        self,
        chat_id: int,
        media: PreparedMedia,
        *,
        caption: str | None = None,
        parse_mode: str | None = None,
        filename: str | None = None,
    ) -> DeliveredMedia:
        self.calls.append((chat_id, media, caption, parse_mode, filename))
        if self.error is not None:
            raise self.error
        return DeliveredMedia(message_id=1, file_id=None)

    async def send_text(self, chat_id: int, text: str) -> None:
        return None


class _FakeQuery:
    def __init__(self, data: str, *, photo: bool = False) -> None:
        self.data = data
        self.answers: list[tuple[str | None, bool]] = []
        self.edits: list[tuple[str, dict[str, Any]]] = []
        self.captions: list[tuple[str, dict[str, Any]]] = []
        self.message = SimpleNamespace(photo=[object()] if photo else None)

    async def answer(self, text: str | None = None, show_alert: bool = False) -> None:
        self.answers.append((text, show_alert))

    async def edit_message_text(self, text: str, **kwargs: Any) -> None:
        self.edits.append((text, kwargs))

    async def edit_message_caption(self, caption: str, **kwargs: Any) -> None:
        self.captions.append((caption, kwargs))


def _prepared() -> PreparedDownload:
    return PreparedDownload(
        normalized=NormalizedURL(
            url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            platform="youtube",
            content_type="public_video",
            host="www.youtube.com",
            source_id="dQw4w9WgXcQ",
        ),
        metadata=MediaMetadata(
            title="Example video",
            duration_seconds=12.0,
            is_live=False,
            webpage_url=None,
            extractor="youtube",
            formats=(),
            uploader="Example Publisher",
        ),
        selection=FormatSelection(
            format_spec="18",
            video_format_id="18",
            audio_format_id=None,
            expected_height=360,
            estimated_bytes=1000,
            combined=True,
        ),
        media=PreparedMedia(
            path=Path("/tmp/v0-output.mp4"),
            probe=ProbeResult(
                duration_seconds=12.0,
                width=640,
                height=360,
                video_codec="h264",
                audio_codec="aac",
                format_name="mp4",
                size_bytes=1234,
            ),
            mime_type="video/mp4",
        ),
    )


def _state(**overrides: object) -> BotV0State:
    values: dict[str, object] = {
        "daily_limit": 5,
        "max_height": 480,
        "max_bytes": 48 * 1024**2,
        "max_duration_seconds": 600,
        "job_timeout_seconds": 30,
        "media_root": Path("/tmp/v0-test"),
        "allowed_user_ids": frozenset(),
        "max_active_jobs_per_user": 1,
    }
    values.update(overrides)
    return BotV0State(BotV0Config(**values))  # type: ignore[arg-type]


def _update(text: str = URL, *, update_id: int = 1, user_id: int = 7) -> tuple[Any, _FakeMessage]:
    message = _FakeMessage(text)
    update = SimpleNamespace(
        update_id=update_id,
        effective_message=message,
        effective_user=SimpleNamespace(id=user_id),
        callback_query=None,
    )
    return cast(Any, update), message


def _context(
    state: BotV0State,
    engine: _FakeEngine,
    delivery: _FakeDelivery,
    *,
    bot: _FakeBot | None = None,
) -> Any:
    return cast(
        Any,
        SimpleNamespace(
            bot=bot or _FakeBot(),
            application=SimpleNamespace(
                bot_data={"v0_state": state, "engine": engine, "delivery": delivery}
            ),
        ),
    )


def _callback(data: str, *, photo: bool = False, user_id: int = 7) -> tuple[Any, _FakeQuery]:
    query = _FakeQuery(data, photo=photo)
    update = SimpleNamespace(
        update_id=9,
        effective_message=None,
        effective_user=SimpleNamespace(id=user_id),
        callback_query=query,
    )
    return cast(Any, update), query


def _reply_texts(message: _FakeMessage) -> list[str]:
    return [text for text, _ in message.replies]


def _edit_texts(message: _FakeMessage) -> list[str]:
    return [text for text, _ in message.edits]


async def test_delivers_and_counts_only_on_success() -> None:
    state = _state()
    engine = _FakeEngine(prepared=_prepared())
    delivery = _FakeDelivery()
    update, message = _update()

    await handle_message(update, _context(state, engine, delivery))

    assert _reply_texts(message) == [messages.accepted_text()]
    assert _edit_texts(message) == [messages.done_text()]
    assert message.edits[0][1]["parse_mode"] == "HTML"
    assert message.edits[0][1]["reply_markup"] is not None
    assert state.usage.used(7) == 1
    assert len(delivery.calls) == 1
    caption, parse_mode, filename = (
        delivery.calls[0][2],
        delivery.calls[0][3],
        delivery.calls[0][4],
    )
    assert caption is not None
    assert "<b>Example video</b>" in caption
    assert "by Example Publisher" in caption
    assert "YouTube · 360p" in caption
    assert "@sv_test_bot" not in caption
    assert parse_mode == "HTML"
    assert filename == "youtube-dQw4w9WgXcQ.mp4"


async def test_reports_progress_stages() -> None:
    state = _state()
    engine = _FakeEngine(
        prepared=_prepared(),
        stages=["inspecting", "downloading", "preparing"],
    )
    update, message = _update()

    await handle_message(update, _context(state, engine, _FakeDelivery()))

    assert _edit_texts(message) == [
        messages.stage_text("inspecting"),
        messages.stage_text("downloading"),
        messages.stage_text("preparing"),
        messages.done_text(),
    ]


async def test_start_sends_branded_logo_card() -> None:
    state = _state()
    update, message = _update()

    await start(update, _context(state, _FakeEngine(), _FakeDelivery()))

    assert len(message.photos) == 1
    caption, kwargs = message.photos[0]
    assert caption is not None and branding.BRAND_NAME in caption
    assert kwargs["parse_mode"] == "HTML"
    assert kwargs["reply_markup"] is not None
    assert branding.logo_path().is_file()


async def test_duplicate_update_is_ignored() -> None:
    state = _state()
    engine = _FakeEngine(prepared=_prepared())
    delivery = _FakeDelivery()
    update, message = _update(update_id=99)
    context = _context(state, engine, delivery)

    await handle_message(update, context)
    await handle_message(update, context)

    assert engine.calls == [URL]
    assert len(message.replies) == 1
    assert state.usage.used(7) == 1


async def test_quota_exhausted_blocks_work() -> None:
    state = _state(daily_limit=1)
    state.usage.record(7)
    engine = _FakeEngine(prepared=_prepared())
    update, message = _update()

    await handle_message(update, _context(state, engine, _FakeDelivery()))

    assert _reply_texts(message) == [messages.quota_exhausted_text(1)]
    assert engine.calls == []


async def test_busy_user_is_rejected() -> None:
    state = _state()
    assert await state.jobs.acquire(7)
    engine = _FakeEngine(prepared=_prepared())
    update, message = _update()

    await handle_message(update, _context(state, engine, _FakeDelivery()))

    assert _reply_texts(message) == [messages.busy_text()]
    assert engine.calls == []


async def test_non_url_text_gets_hint() -> None:
    state = _state()
    engine = _FakeEngine(prepared=_prepared())
    update, message = _update("hello there")

    await handle_message(update, _context(state, engine, _FakeDelivery()))

    assert _reply_texts(message) == [messages.not_a_link_text()]
    assert engine.calls == []


async def test_allow_list_blocks_other_users() -> None:
    state = _state(allowed_user_ids=frozenset({99}))
    engine = _FakeEngine(prepared=_prepared())
    update, message = _update()

    await handle_message(update, _context(state, engine, _FakeDelivery()))

    assert _reply_texts(message) == [messages.private_beta_text()]
    assert engine.calls == []


async def test_engine_error_does_not_consume_quota() -> None:
    state = _state()
    error = AppError(ErrorCode.DURATION_LIMIT, "This video is longer than the supported limit.")
    engine = _FakeEngine(error=error)
    delivery = _FakeDelivery()
    update, message = _update()

    await handle_message(update, _context(state, engine, delivery))

    assert _edit_texts(message) == [messages.rejection_text(error.safe_message)]
    assert state.usage.used(7) == 0
    assert delivery.calls == []


async def test_delivery_failure_does_not_consume_quota() -> None:
    state = _state()
    engine = _FakeEngine(prepared=_prepared())
    delivery = _FakeDelivery(TelegramDeliveryError())
    update, message = _update()

    await handle_message(update, _context(state, engine, delivery))

    assert len(message.edits) == 1
    assert "could not be delivered" in message.edits[0][0]
    assert state.usage.used(7) == 0


async def test_status_reports_usage_and_limits() -> None:
    state = _state()
    state.usage.record(7)
    update, message = _update()

    await status_command(update, _context(state, _FakeEngine(), _FakeDelivery()))

    assert len(message.replies) == 1
    text, kwargs = message.replies[0]
    assert "1 of 5 used (4 left)" in text
    assert "Quality: up to 480p" in text
    assert "Duration: up to 10m 0s" in text
    assert kwargs["reply_markup"] is not None


async def test_callback_help_edits_text_card() -> None:
    state = _state()
    update, query = _callback("help")

    await card_callback(update, _context(state, _FakeEngine(), _FakeDelivery()))

    assert query.answers == [(None, False)]
    assert len(query.edits) == 1
    assert "How it works" in query.edits[0][0]
    assert query.edits[0][1]["reply_markup"] is not None


async def test_callback_status_edits_photo_caption() -> None:
    state = _state()
    state.usage.record(7)
    update, query = _callback("status", photo=True)

    await card_callback(update, _context(state, _FakeEngine(), _FakeDelivery()))

    assert query.edits == []
    assert len(query.captions) == 1
    assert "Your status" in query.captions[0][0]
    assert "1 of 5 used (4 left)" in query.captions[0][0]


async def test_callback_from_disallowed_user_shows_alert() -> None:
    state = _state(allowed_user_ids=frozenset({99}))
    update, query = _callback("help")

    await card_callback(update, _context(state, _FakeEngine(), _FakeDelivery()))

    assert query.answers == [(messages.private_beta_text(), True)]
    assert query.edits == []
