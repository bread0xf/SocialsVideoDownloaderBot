from typing import Any, cast

from telegram import InputProfilePhotoStatic

from apps.bot_v0 import branding
from apps.bot_v0.setup import configure_profile


class _FakeBot:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    async def set_my_name(self, name: str) -> bool:
        self.calls.append(("name", name))
        return True

    async def set_my_short_description(self, short_description: str) -> bool:
        self.calls.append(("short_description", short_description))
        return True

    async def set_my_description(self, description: str) -> bool:
        self.calls.append(("description", description))
        return True

    async def set_my_commands(self, commands: Any) -> bool:
        self.calls.append(("commands", commands))
        return True

    async def set_my_profile_photo(self, photo: Any, **kwargs: Any) -> bool:
        self.calls.append(("photo", photo))
        return True


async def test_configure_profile_sets_name_copy_commands_and_logo() -> None:
    bot = _FakeBot()

    await configure_profile(cast(Any, bot))

    names = [name for name, _ in bot.calls]
    assert names == ["name", "short_description", "description", "commands", "photo"]
    assert bot.calls[0][1] == branding.BRAND_NAME
    assert list(bot.calls[3][1]) == list(branding.COMMANDS)
    assert isinstance(bot.calls[4][1], InputProfilePhotoStatic)
    assert branding.logo_path().is_file()
