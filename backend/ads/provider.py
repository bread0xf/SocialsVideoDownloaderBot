from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class AdOffer:
    """A provider-neutral sponsored message ready to be delivered to a user."""

    text_html: str
    click_url: str
    button_name: str
    image_url: str | None = None
    button_reward_name: str | None = None
    reward_url: str | None = None

    def buttons(self) -> list[list[tuple[str, str]]]:
        """Return inline-keyboard rows. The reward button needs both label and URL."""
        rows: list[list[tuple[str, str]]] = []
        if self.click_url:
            rows.append([(self.button_name or "Open", self.click_url)])
        if self.button_reward_name and self.reward_url:
            rows.append([(self.button_reward_name, self.reward_url)])
        return rows


class AdProviderError(Exception):
    """Raised when an ad provider cannot serve a request.

    The message is safe to show to users. ``reason`` is a stable, log-safe code and
    ``status`` mirrors the provider's HTTP status when one was received.
    """

    def __init__(
        self,
        reason: str,
        *,
        status: int = 0,
        safe_message: str = "The ad service is temporarily unavailable. Please try again later.",
    ) -> None:
        super().__init__(safe_message)
        self.reason = reason
        self.status = status
        self.safe_message = safe_message


class AdProvider(Protocol):
    """Minimal contract for a rewarded-ad network.

    Implementations own their transport. Callers never import provider SDKs.
    """

    async def fetch_ad(self, *, telegram_user_id: int, language: str = "") -> AdOffer | None: ...
