"""Composed Discord administration service used by the MCP server."""

from services.discord_admin_extensions import DiscordAdminExtensions
from services.discord_admin_service import DiscordAdminService


class ExtendedDiscordAdminService(DiscordAdminExtensions, DiscordAdminService):
    """DiscordAdminService plus the extended semantic administration surface."""


# One shared facade over the live bot, matching the existing service lifetime model.
discord_admin_service = ExtendedDiscordAdminService()
