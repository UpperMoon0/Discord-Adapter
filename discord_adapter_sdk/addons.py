"""Stable lifecycle contract for out-of-tree Discord Adapter addons."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from discord.ext import commands

DISCORD_ADDON_ENTRYPOINT_GROUP = "discord_adapter.addons"


@dataclass(frozen=True, slots=True)
class DiscordAddonContext:
    """Minimal host context exposed to an addon.

    Keep this deliberately small. Addons may register application commands,
    listeners, views, and other Discord features through the bot, but should
    not depend on Discord Adapter's private services.
    """

    bot: commands.Bot


@runtime_checkable
class DiscordAddon(Protocol):
    """Protocol implemented by independently packaged Discord addons."""

    name: str

    async def setup(self, context: DiscordAddonContext) -> None:
        """Register the addon's Discord surface on the supplied bot."""
