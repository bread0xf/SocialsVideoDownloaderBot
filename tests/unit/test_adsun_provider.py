from typing import Any

import pytest
from adsun import AdsunError, BotAd

from backend.ads import adsun as adsun_module
from backend.ads.adsun import AdsunProvider, build_adsun_provider, to_ad_offer
from backend.ads.provider import AdOffer, AdProviderError
from backend.core.config import Settings


class _FakeClient:
    def __init__(
        self,
        *,
        result: BotAd | None = None,
        error: Exception | None = None,
    ) -> None:
        self.result = result
        self.error = error
        self.calls: list[tuple[int | str, str]] = []

    def get_ad(self, user_id: int | str, language: str = "") -> BotAd | None:
        self.calls.append((user_id, language))
        if self.error is not None:
            raise self.error
        return self.result


class _RecordingLogger:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def warning(self, event: str, **kwargs: Any) -> None:
        self.calls.append((event, kwargs))

    def error(self, event: str, **kwargs: Any) -> None:
        self.calls.append((event, kwargs))


def _ad(**overrides: Any) -> BotAd:
    values: dict[str, Any] = {
        "text_html": "<b>Sponsored</b>",
        "click_url": "https://adsun.io/click",
        "button_name": "Open",
        "image_url": "https://cdn.adsun.io/ad.jpg",
        "button_reward_name": "Claim reward",
        "reward_url": "https://adsun.io/reward",
    }
    values.update(overrides)
    return BotAd(**values)


def _provider(client: _FakeClient) -> AdsunProvider:
    return AdsunProvider(token="secret-token", block_id="50001", client=client)


async def test_fetch_ad_maps_every_field() -> None:
    client = _FakeClient(result=_ad())

    offer = await _provider(client).fetch_ad(telegram_user_id=777, language="en")

    assert offer == AdOffer(
        text_html="<b>Sponsored</b>",
        click_url="https://adsun.io/click",
        button_name="Open",
        image_url="https://cdn.adsun.io/ad.jpg",
        button_reward_name="Claim reward",
        reward_url="https://adsun.io/reward",
    )
    assert client.calls == [(777, "en")]


async def test_fetch_ad_returns_none_on_no_fill() -> None:
    assert await _provider(_FakeClient(result=None)).fetch_ad(telegram_user_id=777) is None


async def test_empty_image_is_dropped() -> None:
    offer = await _provider(_FakeClient(result=_ad(image_url=""))).fetch_ad(telegram_user_id=777)

    assert offer is not None
    assert offer.image_url is None


async def test_missing_button_name_defaults_to_open() -> None:
    offer = await _provider(_FakeClient(result=_ad(button_name=""))).fetch_ad(telegram_user_id=777)

    assert offer is not None
    assert offer.button_name == "Open"


async def test_non_https_urls_are_dropped() -> None:
    offer = to_ad_offer(
        _ad(
            click_url="javascript:alert(1)",
            image_url="http://insecure.example/ad.jpg",
            reward_url="not-a-url",
        )
    )

    assert offer.click_url == ""
    assert offer.image_url is None
    assert offer.reward_url is None


async def test_provider_error_is_translated_without_leaking_the_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recording = _RecordingLogger()
    monkeypatch.setattr(adsun_module, "logger", recording)
    client = _FakeClient(error=AdsunError("upstream said secret-token", 500))

    with pytest.raises(AdProviderError) as caught:
        await _provider(client).fetch_ad(telegram_user_id=777)

    error = caught.value
    assert error.reason == "adsun_request_failed"
    assert error.status == 500
    assert "secret-token" not in str(error)
    assert "secret-token" not in repr(error.args)
    assert all("secret-token" not in repr(call) for call in recording.calls)


async def test_unexpected_provider_failure_is_translated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recording = _RecordingLogger()
    monkeypatch.setattr(adsun_module, "logger", recording)
    client = _FakeClient(error=RuntimeError("json decode failed for secret-token"))

    with pytest.raises(AdProviderError) as caught:
        await _provider(client).fetch_ad(telegram_user_id=777)

    assert caught.value.reason == "adsun_unexpected_error"
    assert "secret-token" not in str(caught.value)
    assert all("secret-token" not in repr(call) for call in recording.calls)


def test_buttons_include_reward_row_only_when_both_fields_exist() -> None:
    full = AdOffer(
        text_html="x",
        click_url="https://adsun.io/click",
        button_name="Open",
        button_reward_name="Claim",
        reward_url="https://adsun.io/reward",
    )
    partial = AdOffer(
        text_html="x",
        click_url="https://adsun.io/click",
        button_name="Open",
        button_reward_name="Claim",
    )

    assert full.buttons() == [
        [("Open", "https://adsun.io/click")],
        [("Claim", "https://adsun.io/reward")],
    ]
    assert partial.buttons() == [[("Open", "https://adsun.io/click")]]


def test_factory_is_disabled_by_default() -> None:
    assert build_adsun_provider(Settings(_env_file=None, app_env="test")) is None


def test_factory_requires_token_and_block() -> None:
    settings = Settings(
        _env_file=None,
        app_env="test",
        adsun_enabled=True,
        adsun_token="token",
        adsun_block_id="",
    )

    assert build_adsun_provider(settings) is None


def test_factory_builds_provider_when_configured() -> None:
    settings = Settings(
        _env_file=None,
        app_env="test",
        adsun_enabled=True,
        adsun_token="token",
        adsun_block_id="bot-50001",
    )

    assert isinstance(build_adsun_provider(settings), AdsunProvider)
