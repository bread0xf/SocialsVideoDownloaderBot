import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from telegram import InlineKeyboardMarkup
from telegram.constants import ParseMode

from apps.bot import main as bot_main
from backend.ads import AdOffer
from backend.ads.provider import AdProviderError
from backend.core.config import Settings
from backend.entitlements.service import Entitlement


class _FakeMessage:
    def __init__(self) -> None:
        self.replies: list[tuple[str, dict[str, Any]]] = []
        self.photos: list[tuple[str | None, dict[str, Any]]] = []

    async def reply_text(self, text: str, **kwargs: Any) -> None:
        self.replies.append((text, kwargs))

    async def reply_photo(
        self,
        photo: str | None = None,
        caption: str | None = None,
        **kwargs: Any,
    ) -> None:
        self.photos.append((caption, {**kwargs, "photo": photo}))


class _FakeUser:
    id = 777
    username = "example"
    first_name = "Example"
    last_name = None
    language_code = "en"


class _FakeCallbackQuery:
    def __init__(self) -> None:
        self.answered = False

    async def answer(self) -> None:
        self.answered = True


class _FakeUpdate:
    def __init__(self) -> None:
        self.update_id = 1
        self.effective_message = _FakeMessage()
        self.effective_user = _FakeUser()
        self.callback_query: _FakeCallbackQuery | None = None


class _FakeProvider:
    def __init__(
        self,
        *,
        offer: AdOffer | None = None,
        error: Exception | None = None,
    ) -> None:
        self.offer = offer
        self.error = error
        self.calls: list[tuple[int, str]] = []

    async def fetch_ad(self, *, telegram_user_id: int, language: str = "") -> AdOffer | None:
        self.calls.append((telegram_user_id, language))
        if self.error is not None:
            raise self.error
        return self.offer


def _context(
    *,
    settings: Settings,
    provider: _FakeProvider | None = None,
    session_factory: Any = None,
) -> Any:
    bot_data: dict[str, Any] = {"settings": settings}
    if provider is not None:
        bot_data["ad_provider"] = provider
    if session_factory is not None:
        bot_data["session_factory"] = session_factory
    return SimpleNamespace(application=SimpleNamespace(bot_data=bot_data))


def _settings(*, enabled: bool = True) -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        adsun_enabled=enabled,
        adsun_block_id="50001",
    )


def _offer(**overrides: Any) -> AdOffer:
    values: dict[str, Any] = {
        "text_html": "<b>Sponsored</b>",
        "click_url": "https://adsun.io/click",
        "button_name": "Open",
    }
    values.update(overrides)
    return AdOffer(**values)


def _entitlement(*, premium: bool, sponsor_eligible: bool) -> Entitlement:
    return Entitlement(
        plan_code="premium" if premium else "free",
        max_resolution_p=2160 if premium else 480,
        daily_included_limit=20 if premium else 5,
        quota_source="premium_included" if premium else "included",
        priority=10 if premium else 0,
        sponsor_eligible=sponsor_eligible,
        evaluated_at=datetime.now(UTC),
        subscription_id=None,
        paid_through=None,
    )


def _patch_reward_session(
    monkeypatch: Any,
    *,
    status: str = "opened",
    cap_resets_at: datetime | None = None,
    open_error: Exception | None = None,
) -> dict[str, Any]:
    """Replace the DB-backed session calls so unit tests stay in-memory."""
    recorded: dict[str, Any] = {
        "opened": 0,
        "expired": [],
        "session_id": uuid.uuid4(),
        "block": None,
    }

    @asynccontextmanager
    async def _scope(_factory: Any) -> Any:
        yield object()

    async def _upsert(*args: Any, **kwargs: Any) -> Any:
        return SimpleNamespace(id=uuid.uuid4())

    async def _open(*args: Any, **kwargs: Any) -> Any:
        if open_error is not None:
            raise open_error
        recorded["opened"] += 1
        recorded["block"] = kwargs.get("block")
        return SimpleNamespace(
            status=status,
            session_id=recorded["session_id"] if status == "opened" else None,
            expires_at=datetime.now(UTC),
            cap_resets_at=cap_resets_at,
        )

    async def _expire(*args: Any, **kwargs: Any) -> bool:
        recorded["expired"].append(kwargs.get("reason"))
        return True

    monkeypatch.setattr(bot_main, "session_scope", _scope)
    monkeypatch.setattr(bot_main, "upsert_telegram_user", _upsert)
    monkeypatch.setattr(bot_main, "open_reward_ad_session", _open)
    monkeypatch.setattr(bot_main, "expire_reward_session", _expire)
    return recorded


async def test_reward_command_sends_html_protected_message_with_buttons(
    monkeypatch: Any,
) -> None:
    _patch_reward_session(monkeypatch)
    provider = _FakeProvider(offer=_offer())
    update = _FakeUpdate()

    await bot_main.reward_command(
        update,
        _context(settings=_settings(), provider=provider, session_factory=object()),
    )  # type: ignore[arg-type]

    assert provider.calls == [(777, "en")]
    text, kwargs = update.effective_message.replies[0]
    assert text == "<b>Sponsored</b>"
    assert kwargs["parse_mode"] == ParseMode.HTML
    assert kwargs["protect_content"] is True
    markup = kwargs["reply_markup"]
    assert isinstance(markup, InlineKeyboardMarkup)
    assert markup.inline_keyboard[0][0].url == "https://adsun.io/click"
    assert update.effective_message.replies[1][0] == bot_main.REWARD_PENDING_TEXT


async def test_reward_command_sends_photo_when_ad_has_an_image(
    monkeypatch: Any,
) -> None:
    _patch_reward_session(monkeypatch)
    provider = _FakeProvider(
        offer=_offer(
            image_url="https://cdn.adsun.io/ad.jpg",
            button_reward_name="Claim",
            reward_url="https://adsun.io/reward",
        )
    )
    update = _FakeUpdate()

    await bot_main.reward_command(
        update,
        _context(settings=_settings(), provider=provider, session_factory=object()),
    )  # type: ignore[arg-type]

    caption, kwargs = update.effective_message.photos[0]
    assert caption == "<b>Sponsored</b>"
    assert kwargs["parse_mode"] == ParseMode.HTML
    assert kwargs["protect_content"] is True
    assert kwargs["photo"] == "https://cdn.adsun.io/ad.jpg"
    markup = kwargs["reply_markup"]
    assert isinstance(markup, InlineKeyboardMarkup)
    assert len(markup.inline_keyboard) == 2


async def test_no_fill_returns_a_friendly_message_and_expires_the_session(
    monkeypatch: Any,
) -> None:
    recorded = _patch_reward_session(monkeypatch)
    provider = _FakeProvider(offer=None)
    update = _FakeUpdate()

    await bot_main.reward_command(
        update,
        _context(settings=_settings(), provider=provider, session_factory=object()),
    )  # type: ignore[arg-type]

    assert update.effective_message.replies == [(bot_main.REWARD_NO_AD_TEXT, {})]
    assert recorded["expired"] == ["no_fill"]


async def test_provider_error_returns_a_friendly_message_and_expires_the_session(
    monkeypatch: Any,
) -> None:
    recorded = _patch_reward_session(monkeypatch)
    provider = _FakeProvider(error=AdProviderError("adsun_request_failed", status=500))
    update = _FakeUpdate()

    await bot_main.reward_command(
        update,
        _context(settings=_settings(), provider=provider, session_factory=object()),
    )  # type: ignore[arg-type]

    assert update.effective_message.replies == [(bot_main.REWARD_ERROR_TEXT, {})]
    assert recorded["expired"] == ["provider_error"]


async def test_pending_session_blocks_a_second_ad_fetch(monkeypatch: Any) -> None:
    _patch_reward_session(monkeypatch, status="reused")
    provider = _FakeProvider(offer=_offer())
    update = _FakeUpdate()

    await bot_main.reward_command(
        update,
        _context(settings=_settings(), provider=provider, session_factory=object()),
    )  # type: ignore[arg-type]

    assert provider.calls == []
    assert update.effective_message.replies == [(bot_main.REWARD_SESSION_PENDING_TEXT, {})]


async def test_capped_user_is_told_when_the_cap_resets(monkeypatch: Any) -> None:
    resets_at = datetime(2026, 11, 18, 23, 0, tzinfo=UTC)
    _patch_reward_session(monkeypatch, status="capped", cap_resets_at=resets_at)
    provider = _FakeProvider(offer=_offer())
    update = _FakeUpdate()

    await bot_main.reward_command(
        update,
        _context(settings=_settings(), provider=provider, session_factory=object()),
    )  # type: ignore[arg-type]

    assert provider.calls == []
    replies = [text for text, _ in update.effective_message.replies]
    assert replies == [bot_main._reward_cap_text(resets_at)]
    assert "Africa/Lagos" in replies[0]
    assert "23:00 UTC" in replies[0]


async def test_premium_user_does_not_get_an_ad(monkeypatch: Any) -> None:
    _patch_reward_session(monkeypatch, status="premium_ineligible")
    provider = _FakeProvider(offer=_offer())
    update = _FakeUpdate()

    await bot_main.reward_command(
        update,
        _context(settings=_settings(), provider=provider, session_factory=object()),
    )  # type: ignore[arg-type]

    assert provider.calls == []
    assert update.effective_message.replies == [(bot_main.REWARD_PREMIUM_TEXT, {})]


async def test_blocked_user_does_not_get_an_ad(monkeypatch: Any) -> None:
    _patch_reward_session(monkeypatch, status="blocked")
    provider = _FakeProvider(offer=_offer())
    update = _FakeUpdate()

    await bot_main.reward_command(
        update,
        _context(settings=_settings(), provider=provider, session_factory=object()),
    )  # type: ignore[arg-type]

    assert provider.calls == []
    assert update.effective_message.replies == [(bot_main.REWARD_BLOCKED_TEXT, {})]


async def test_session_open_failure_does_not_serve_an_uncreditable_ad(
    monkeypatch: Any,
) -> None:
    _patch_reward_session(monkeypatch, open_error=RuntimeError("database unavailable"))
    provider = _FakeProvider(offer=_offer())
    update = _FakeUpdate()

    await bot_main.reward_command(
        update,
        _context(settings=_settings(), provider=provider, session_factory=object()),
    )  # type: ignore[arg-type]

    assert provider.calls == []
    assert update.effective_message.replies == [(bot_main.REWARD_ERROR_TEXT, {})]


async def test_missing_session_store_refuses_to_serve(monkeypatch: Any) -> None:
    _patch_reward_session(monkeypatch)
    provider = _FakeProvider(offer=_offer())
    update = _FakeUpdate()

    await bot_main.reward_command(
        update,
        _context(settings=_settings(), provider=provider),
    )  # type: ignore[arg-type]

    assert provider.calls == []
    assert update.effective_message.replies == [(bot_main.REWARD_ERROR_TEXT, {})]


async def test_disabled_feature_replies_without_calling_the_provider() -> None:
    provider = _FakeProvider(offer=_offer())
    update = _FakeUpdate()

    await bot_main.reward_command(
        update,
        _context(settings=_settings(enabled=False), provider=provider),  # type: ignore[arg-type]
    )

    assert provider.calls == []
    assert update.effective_message.replies == [(bot_main.REWARD_DISABLED_TEXT, {})]


async def test_missing_provider_is_treated_as_disabled() -> None:
    update = _FakeUpdate()

    await bot_main.reward_command(update, _context(settings=_settings()))  # type: ignore[arg-type]

    assert update.effective_message.replies == [(bot_main.REWARD_DISABLED_TEXT, {})]


async def test_callback_query_answers_and_sends_the_ad(monkeypatch: Any) -> None:
    _patch_reward_session(monkeypatch)
    provider = _FakeProvider(offer=_offer())
    update = _FakeUpdate()
    query = _FakeCallbackQuery()
    update.callback_query = query

    await bot_main.reward_callback(
        update,
        _context(settings=_settings(), provider=provider, session_factory=object()),
    )  # type: ignore[arg-type]

    assert query.answered is True
    assert update.effective_message.replies[0][0] == "<b>Sponsored</b>"


def test_reward_markup_is_offered_to_free_plans_only() -> None:
    free = bot_main.reward_markup_for(_entitlement(premium=False, sponsor_eligible=True))
    premium = bot_main.reward_markup_for(_entitlement(premium=True, sponsor_eligible=False))

    assert isinstance(free, InlineKeyboardMarkup)
    assert free.inline_keyboard[0][0].callback_data == bot_main.REWARD_CALLBACK
    assert premium is None


async def test_reward_keyboard_skips_disabled_or_unconfigured_contexts() -> None:
    identity = bot_main.TelegramIdentity(telegram_user_id=777)  # type: ignore[attr-defined]

    disabled = _context(settings=_settings(enabled=False))
    enabled_without_session = _context(settings=_settings())

    assert await bot_main._reward_keyboard(disabled, identity) is None
    assert await bot_main._reward_keyboard(enabled_without_session, identity) is None


async def test_quota_exhausted_still_replies_when_the_reward_button_fails(
    monkeypatch: Any,
) -> None:
    update = _FakeUpdate()

    def _normalize(_: str) -> Any:
        return SimpleNamespace(platform="youtube", host="youtube.com")

    async def _resolve(_: str) -> None:
        return None

    class _Session:
        async def __aenter__(self) -> "_Session":
            return self

        async def __aexit__(self, *_: object) -> bool:
            return False

        async def commit(self) -> None:
            return None

        async def rollback(self) -> None:
            return None

    async def _upsert(*_: object, **__: object) -> Any:
        return SimpleNamespace(id="user-id")

    async def _submit(*_: object, **__: object) -> Any:
        raise bot_main.AppError(bot_main.ErrorCode.QUOTA_EXHAUSTED, "Daily limit reached.")

    async def _broken_keyboard(*_: object, **__: object) -> Any:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(bot_main, "normalize_url", _normalize)
    monkeypatch.setattr(bot_main, "resolve_public_addresses", _resolve)
    monkeypatch.setattr(bot_main, "upsert_telegram_user", _upsert)
    monkeypatch.setattr(bot_main, "submit_download", _submit)
    monkeypatch.setattr(bot_main, "_reward_keyboard", _broken_keyboard)

    context = _context(settings=_settings(), session_factory=lambda: _Session())
    update.effective_message.text = "https://youtu.be/dQw4w9WgXcQ"  # type: ignore[attr-defined]

    await bot_main.handle_url(update, context)  # type: ignore[arg-type]

    assert update.effective_message.replies == [("Daily limit reached.", {"reply_markup": None})]
