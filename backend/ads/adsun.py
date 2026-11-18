import asyncio
from typing import Protocol

import structlog
from adsun import AdsunBot, AdsunError, BotAd

from backend.ads.provider import AdOffer, AdProviderError
from backend.core.config import Settings

logger = structlog.get_logger(__name__)

DEFAULT_API_URL = "https://api.adsun.io"


class _AdsunClient(Protocol):
    def get_ad(self, user_id: int | str, language: str = "") -> BotAd | None: ...


def _https_url(value: str | None) -> str | None:
    """Keep only absolute HTTPS URLs we are willing to hand to Telegram."""
    if not value:
        return None
    return value if value.startswith("https://") else None


def to_ad_offer(ad: BotAd) -> AdOffer:
    return AdOffer(
        text_html=ad.text_html,
        click_url=_https_url(ad.click_url) or "",
        button_name=ad.button_name or "Open",
        image_url=_https_url(ad.image_url),
        button_reward_name=ad.button_reward_name,
        reward_url=_https_url(ad.reward_url),
    )


class AdsunProvider:
    """Adsun adapter.

    The Adsun SDK is an implementation detail of this module. It uses the
    dependency-free standard-library client off-thread so the bot's event loop is
    never blocked; the SDK's async client would require the optional aiohttp extra.
    """

    def __init__(
        self,
        *,
        token: str,
        block_id: str,
        api_url: str = DEFAULT_API_URL,
        timeout: float = 10.0,
        client: _AdsunClient | None = None,
    ) -> None:
        self._client = client or AdsunBot(
            token=token,
            block_id=block_id,
            api_url=api_url,
            timeout=timeout,
        )

    async def fetch_ad(self, *, telegram_user_id: int, language: str = "") -> AdOffer | None:
        try:
            ad = await asyncio.to_thread(self._client.get_ad, telegram_user_id, language)
        except AdsunError as exc:
            # Log the status only. Never the request URL, query or account token.
            logger.warning("adsun_ad_request_failed", status=exc.status)
            raise AdProviderError("adsun_request_failed", status=exc.status) from None
        except Exception:
            logger.warning("adsun_ad_request_failed", status=0)
            raise AdProviderError("adsun_unexpected_error") from None

        if ad is None:
            return None
        return to_ad_offer(ad)


def build_adsun_provider(settings: Settings) -> AdsunProvider | None:
    """Construct the provider only when enabled and fully configured.

    Secrets are validated at the use site because the bot and API run with
    different environment variables. Never log the account token.
    """
    if not settings.adsun_enabled:
        return None

    if not settings.adsun_configured:
        logger.error("adsun_enabled_but_not_configured")
        return None

    return AdsunProvider(token=settings.adsun_account_token, block_id=settings.adsun_block_id)
