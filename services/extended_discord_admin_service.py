"""Composed Discord administration service used by the MCP server."""

import discord

from services.access_policy_service import access_policy_service
from services.discord_admin_extensions import DiscordAdminExtensions
from services.discord_admin_service import DiscordAdminService


class ExtendedDiscordAdminService(DiscordAdminExtensions, DiscordAdminService):
    """DiscordAdminService plus runtime policy and the extended semantic surface."""

    def is_guild_allowed(self, guild_id: int) -> bool:
        """Use the immutable Redis-backed runtime snapshot for every guild check."""
        return access_policy_service.is_guild_allowed(guild_id)

    def policy_status(self) -> dict:
        return access_policy_service.status()

    def _guild(self, guild_id: int) -> tuple[discord.Guild | None, dict | None]:
        if not self.is_guild_allowed(guild_id):
            return None, {
                "success": False,
                "message": (
                    f"Guild {guild_id} is not enabled for MCP administration. "
                    "Inspect discord_get_access_policy and use a privileged policy mutation tool if a change is intended."
                ),
            }
        guild = self.bot_service.bot.get_guild(guild_id)
        if guild is None:
            return None, {"success": False, "message": f"Guild {guild_id} not found"}
        return guild, None

    async def list_guilds(self) -> dict:
        """List allowed guilds and every permission family used by exposed tools."""

        async def op() -> dict:
            guilds = []
            for guild in self.bot_service.bot.guilds:
                if not self.is_guild_allowed(guild.id):
                    continue

                me = guild.me
                perms = me.guild_permissions if me else discord.Permissions.none()
                guilds.append(
                    {
                        "id": guild.id,
                        "name": guild.name,
                        "member_count": guild.member_count,
                        "owner_id": guild.owner_id,
                        "text_channel_count": len(guild.text_channels),
                        "voice_channel_count": len(guild.voice_channels),
                        "capabilities": {
                            "manage_messages": perms.manage_messages,
                            "moderate_members": perms.moderate_members,
                            "kick_members": perms.kick_members,
                            "ban_members": perms.ban_members,
                            "manage_roles": perms.manage_roles,
                            "manage_channels": perms.manage_channels,
                            "manage_guild": perms.manage_guild,
                            "manage_webhooks": perms.manage_webhooks,
                            "manage_emojis_and_stickers": perms.manage_emojis_and_stickers,
                            "manage_nicknames": perms.manage_nicknames,
                            "move_members": perms.move_members,
                            "mute_members": perms.mute_members,
                            "deafen_members": perms.deafen_members,
                            "manage_threads": perms.manage_threads,
                            "create_public_threads": perms.create_public_threads,
                            "create_private_threads": perms.create_private_threads,
                            "create_instant_invite": perms.create_instant_invite,
                            "view_audit_log": perms.view_audit_log,
                        },
                    }
                )

            return {
                "success": True,
                "guilds": guilds,
                "count": len(guilds),
                "policy": self.policy_status(),
            }

        return await self._run(op)


# One shared facade over the live bot, matching the existing service lifetime model.
discord_admin_service = ExtendedDiscordAdminService()
