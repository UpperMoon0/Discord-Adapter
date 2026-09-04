"""Composed Discord administration service used by the MCP server."""

import discord
from typing import Any

from services.discord_admin_extensions import DiscordAdminExtensions
from services.discord_admin_service import DiscordAdminService


class ExtendedDiscordAdminService(DiscordAdminExtensions, DiscordAdminService):
    """DiscordAdminService plus the extended semantic administration surface."""

    async def configure_channel(
        self,
        guild_id: int,
        channel_id: int,
        *,
        name: str | None = None,
        topic: str | None = None,
        slowmode_delay: int | None = None,
        position: int | None = None,
        category_id: int | None = None,
        clear_category: bool = False,
        sync_permissions: bool | None = None,
        reason: str = "",
    ) -> dict:
        """Consolidated channel edit used by the compact MCP surface."""
        if name is not None:
            name = name.strip()
            if not 1 <= len(name) <= 100:
                return {"success": False, "message": "channel name must contain 1-100 characters"}
        if topic is not None and len(topic) > 1024:
            return {"success": False, "message": "channel topic must be at most 1024 characters"}
        if slowmode_delay is not None and not 0 <= slowmode_delay <= 21_600:
            return {"success": False, "message": "slowmode_delay must be between 0 and 21600 seconds"}
        if position is not None and position < 0:
            return {"success": False, "message": "channel position must be zero or greater"}
        if category_id is not None and clear_category:
            return {"success": False, "message": "cannot set and clear category in one request"}
        if clear_category and sync_permissions:
            return {"success": False, "message": "cannot sync permissions while clearing the category"}

        async def op() -> dict:
            guild, guild_error = self._guild(guild_id)
            if guild_error:
                return guild_error
            channel = guild.get_channel(channel_id)
            if channel is None or not hasattr(channel, "edit"):
                return {"success": False, "message": f"Guild channel {channel_id} not found"}

            kwargs: dict[str, Any] = {"reason": self._reason(reason)}
            if name is not None:
                kwargs["name"] = name
            if topic is not None:
                if not isinstance(channel, discord.TextChannel):
                    return {"success": False, "message": "topic can only be changed on text channels"}
                kwargs["topic"] = topic
            if slowmode_delay is not None:
                if not isinstance(channel, discord.TextChannel):
                    return {"success": False, "message": "slowmode_delay can only be changed on text channels"}
                kwargs["slowmode_delay"] = slowmode_delay
            if position is not None:
                kwargs["position"] = position
            if clear_category:
                if isinstance(channel, discord.CategoryChannel):
                    return {"success": False, "message": "category channels cannot have a parent category"}
                kwargs["category"] = None
            elif category_id is not None:
                category = guild.get_channel(category_id)
                if not isinstance(category, discord.CategoryChannel):
                    return {"success": False, "message": f"Category {category_id} not found"}
                if isinstance(channel, discord.CategoryChannel):
                    return {"success": False, "message": "category channels cannot have a parent category"}
                kwargs["category"] = category
            if sync_permissions is not None:
                if isinstance(channel, discord.CategoryChannel):
                    return {"success": False, "message": "category channels cannot sync permissions from a parent"}
                kwargs["sync_permissions"] = sync_permissions
            if len(kwargs) == 1:
                return {"success": False, "message": "no channel changes were provided"}

            edited = await channel.edit(**kwargs)
            return {
                "success": True,
                "guild_id": guild.id,
                "channel_id": edited.id,
                "channel_name": edited.name,
                "channel_type": str(getattr(edited, "type", "unknown")),
                "position": getattr(edited, "position", None),
                "category_id": getattr(edited, "category_id", None),
            }

        return await self._run(op)

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
