"""Guild-scoped Discord administration used by MCP."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import timedelta
from typing import Awaitable, Callable, TypeVar

import discord

from services.bot_service import bot_service

logger = logging.getLogger("lily-discord-adapter")
T = TypeVar("T")


class DiscordAdminService:
    """Safe facade around the live discord.py bot."""

    def __init__(self):
        self.bot_service = bot_service

    @staticmethod
    def _configured_guild_ids() -> set[int] | None:
        raw = os.getenv("DISCORD_ADMIN_GUILD_IDS", "").strip()
        if not raw:
            return None
        if raw == "*":
            return set()  # empty set is the explicit "all" sentinel

        result: set[int] = set()
        for value in raw.split(","):
            value = value.strip()
            if not value:
                continue
            try:
                result.add(int(value))
            except ValueError:
                logger.warning("Ignoring invalid DISCORD_ADMIN_GUILD_IDS entry: %s", value)
        return result

    def is_guild_allowed(self, guild_id: int) -> bool:
        configured = self._configured_guild_ids()
        return configured is not None and (not configured or guild_id in configured)

    def policy_status(self) -> dict:
        raw = os.getenv("DISCORD_ADMIN_GUILD_IDS", "").strip()
        configured = self._configured_guild_ids()
        return {
            "configured": bool(raw),
            "all_guilds": raw == "*",
            "guild_ids": sorted(configured) if configured else [],
        }

    def _bot_ready_error(self) -> dict | None:
        bot = self.bot_service.bot
        if bot is None:
            return {"success": False, "message": "Discord bot is not initialized"}
        if bot.is_closed():
            return {"success": False, "message": "Discord bot is not running"}
        if not bot.is_ready():
            return {"success": False, "message": "Discord bot is not ready"}
        return None

    async def _on_bot_loop(self, operation: Callable[[], Awaitable[T]]) -> T:
        bot_loop = self.bot_service.bot_loop
        current_loop = asyncio.get_running_loop()
        if bot_loop and bot_loop.is_running() and bot_loop is not current_loop:
            future = asyncio.run_coroutine_threadsafe(operation(), bot_loop)
            return await asyncio.wrap_future(future)
        return await operation()

    async def _run(self, operation: Callable[[], Awaitable[dict]]) -> dict:
        ready_error = self._bot_ready_error()
        if ready_error:
            return ready_error
        try:
            return await self._on_bot_loop(operation)
        except discord.Forbidden as exc:
            return {"success": False, "message": f"Discord permission denied: {exc}"}
        except discord.NotFound as exc:
            return {"success": False, "message": f"Discord resource not found: {exc}"}
        except discord.HTTPException as exc:
            return {"success": False, "message": f"Discord API request failed: {exc}"}
        except Exception as exc:
            logger.exception("Discord admin operation failed")
            return {"success": False, "message": f"Discord admin operation failed: {exc}"}

    def _guild(self, guild_id: int) -> tuple[discord.Guild | None, dict | None]:
        if not self.is_guild_allowed(guild_id):
            return None, {
                "success": False,
                "message": (
                    f"Guild {guild_id} is not enabled for MCP administration. "
                    "Add it to DISCORD_ADMIN_GUILD_IDS (or explicitly use '*')."
                ),
            }
        guild = self.bot_service.bot.get_guild(guild_id)
        if guild is None:
            return None, {"success": False, "message": f"Guild {guild_id} not found"}
        return guild, None

    @staticmethod
    def _channel(guild: discord.Guild, channel_id: int):
        return guild.get_channel(channel_id) or guild.get_thread(channel_id)

    @staticmethod
    def _member_summary(member: discord.Member) -> dict:
        return {
            "id": member.id,
            "name": member.name,
            "display_name": member.display_name,
            "global_name": member.global_name,
            "bot": member.bot,
            "roles": [
                {"id": role.id, "name": role.name}
                for role in member.roles
                if not role.is_default()
            ],
            "timed_out_until": (
                member.timed_out_until.isoformat() if member.timed_out_until else None
            ),
        }

    async def list_guilds(self) -> dict:
        async def op() -> dict:
            guilds = []
            for guild in self.bot_service.bot.guilds:
                if not self.is_guild_allowed(guild.id):
                    continue
                me = guild.me
                perms = me.guild_permissions if me else discord.Permissions.none()
                guilds.append({
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
                        "view_audit_log": perms.view_audit_log,
                    },
                })
            return {
                "success": True,
                "guilds": guilds,
                "count": len(guilds),
                "policy": self.policy_status(),
            }
        return await self._run(op)

    async def list_channels(self, guild_id: int) -> dict:
        async def op() -> dict:
            guild, error = self._guild(guild_id)
            if error:
                return error
            channels = [{
                "id": channel.id,
                "name": channel.name,
                "type": str(channel.type),
                "category_id": getattr(channel, "category_id", None),
                "position": channel.position,
            } for channel in guild.channels]
            return {
                "success": True,
                "guild_id": guild.id,
                "guild_name": guild.name,
                "channels": channels,
            }
        return await self._run(op)

    async def find_members(self, guild_id: int, query: str, limit: int = 20) -> dict:
        query = query.strip()
        limit = max(1, min(limit, 50))
        if not query:
            return {"success": False, "message": "query must not be empty"}

        async def op() -> dict:
            guild, error = self._guild(guild_id)
            if error:
                return error
            q = query.casefold()
            matches = [
                member for member in guild.members
                if str(member.id) == query
                or q in member.name.casefold()
                or q in member.display_name.casefold()
                or (member.global_name and q in member.global_name.casefold())
            ][:limit]
            if not matches and not query.isdigit():
                try:
                    matches = await guild.query_members(query=query, limit=limit)
                except (discord.Forbidden, discord.HTTPException):
                    pass
            return {
                "success": True,
                "guild_id": guild.id,
                "query": query,
                "members": [self._member_summary(m) for m in matches],
                "count": len(matches),
            }
        return await self._run(op)

    async def get_member(self, guild_id: int, user_id: int) -> dict:
        async def op() -> dict:
            guild, error = self._guild(guild_id)
            if error:
                return error
            member = guild.get_member(user_id) or await guild.fetch_member(user_id)
            return {"success": True, "guild_id": guild.id, "member": self._member_summary(member)}
        return await self._run(op)

    async def read_messages(self, guild_id: int, channel_id: int, limit: int = 25) -> dict:
        limit = max(1, min(limit, 100))

        async def op() -> dict:
            guild, error = self._guild(guild_id)
            if error:
                return error
            channel = self._channel(guild, channel_id)
            if not isinstance(channel, (discord.TextChannel, discord.Thread)):
                return {"success": False, "message": f"Channel {channel_id} is not a readable text channel"}
            messages = []
            async for message in channel.history(limit=limit):
                messages.append({
                    "id": message.id,
                    "author": {
                        "id": message.author.id,
                        "name": str(message.author),
                        "display_name": getattr(message.author, "display_name", None),
                        "bot": message.author.bot,
                    },
                    "content": message.content,
                    "created_at": message.created_at.isoformat(),
                    "edited_at": message.edited_at.isoformat() if message.edited_at else None,
                    "attachments": [a.url for a in message.attachments],
                    "pinned": message.pinned,
                })
            return {
                "success": True,
                "guild_id": guild.id,
                "channel_id": channel.id,
                "channel_name": channel.name,
                "messages": messages,
                "count": len(messages),
            }
        return await self._run(op)

    async def get_audit_log(self, guild_id: int, limit: int = 25) -> dict:
        limit = max(1, min(limit, 100))

        async def op() -> dict:
            guild, error = self._guild(guild_id)
            if error:
                return error
            entries = []
            async for entry in guild.audit_logs(limit=limit):
                target = entry.target
                entries.append({
                    "id": entry.id,
                    "action": str(entry.action),
                    "actor": {
                        "id": entry.user.id if entry.user else None,
                        "name": str(entry.user) if entry.user else None,
                    },
                    "target": {
                        "id": getattr(target, "id", None),
                        "name": (
                            getattr(target, "name", None) or str(target)
                            if target else None
                        ),
                    },
                    "reason": entry.reason,
                    "created_at": entry.created_at.isoformat(),
                })
            return {
                "success": True,
                "guild_id": guild.id,
                "guild_name": guild.name,
                "entries": entries,
                "count": len(entries),
            }
        return await self._run(op)

    async def send_message(self, guild_id: int, channel_id: int, content: str) -> dict:
        content = content.strip()
        if not content:
            return {"success": False, "message": "content must not be empty"}
        if len(content) > 2000:
            return {"success": False, "message": "content exceeds Discord's 2000-character message limit"}

        async def op() -> dict:
            guild, error = self._guild(guild_id)
            if error:
                return error
            channel = self._channel(guild, channel_id)
            if not isinstance(channel, (discord.TextChannel, discord.Thread)):
                return {"success": False, "message": f"Channel {channel_id} is not a text channel"}
            message = await channel.send(
                content,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return {
                "success": True,
                "guild_id": guild.id,
                "channel_id": channel.id,
                "message_id": message.id,
                "content": content,
            }
        return await self._run(op)

    async def delete_message(
        self, guild_id: int, channel_id: int, message_id: int, reason: str
    ) -> dict:
        async def op() -> dict:
            guild, error = self._guild(guild_id)
            if error:
                return error
            channel = self._channel(guild, channel_id)
            if not isinstance(channel, (discord.TextChannel, discord.Thread)):
                return {"success": False, "message": f"Channel {channel_id} is not a text channel"}
            message = await channel.fetch_message(message_id)
            await message.delete(reason=reason or "MCP admin action")
            return {
                "success": True,
                "guild_id": guild.id,
                "channel_id": channel.id,
                "message_id": message_id,
            }
        return await self._run(op)

    async def _member_action(
        self,
        guild_id: int,
        user_id: int,
        action: Callable[[discord.Member], Awaitable[None]],
    ) -> dict:
        async def op() -> dict:
            guild, error = self._guild(guild_id)
            if error:
                return error
            member = guild.get_member(user_id) or await guild.fetch_member(user_id)
            await action(member)
            return {
                "success": True,
                "guild_id": guild.id,
                "user_id": member.id,
                "display_name": member.display_name,
            }
        return await self._run(op)

    async def timeout_member(
        self, guild_id: int, user_id: int, duration_seconds: int, reason: str
    ) -> dict:
        if not 1 <= duration_seconds <= 2_419_200:
            return {"success": False, "message": "duration_seconds must be between 1 and 2419200 (28 days)"}
        async def action(member):
            await member.timeout(
                timedelta(seconds=duration_seconds),
                reason=reason or "MCP admin action",
            )
        result = await self._member_action(guild_id, user_id, action)
        if result.get("success"):
            result["duration_seconds"] = duration_seconds
        return result

    async def clear_timeout(self, guild_id: int, user_id: int, reason: str) -> dict:
        async def action(member):
            await member.timeout(None, reason=reason or "MCP admin action")
        return await self._member_action(guild_id, user_id, action)

    async def kick_member(self, guild_id: int, user_id: int, reason: str) -> dict:
        async def action(member):
            await member.kick(reason=reason or "MCP admin action")
        return await self._member_action(guild_id, user_id, action)

    async def ban_member(
        self,
        guild_id: int,
        user_id: int,
        reason: str,
        delete_message_seconds: int = 0,
    ) -> dict:
        delete_message_seconds = max(0, min(delete_message_seconds, 604_800))

        async def op() -> dict:
            guild, error = self._guild(guild_id)
            if error:
                return error
            target = guild.get_member(user_id) or discord.Object(id=user_id)
            await guild.ban(
                target,
                reason=reason or "MCP admin action",
                delete_message_seconds=delete_message_seconds,
            )
            return {"success": True, "guild_id": guild.id, "user_id": user_id}
        return await self._run(op)

    async def unban_member(self, guild_id: int, user_id: int, reason: str) -> dict:
        async def op() -> dict:
            guild, error = self._guild(guild_id)
            if error:
                return error
            await guild.unban(
                discord.Object(id=user_id),
                reason=reason or "MCP admin action",
            )
            return {"success": True, "guild_id": guild.id, "user_id": user_id}
        return await self._run(op)

    async def list_roles(self, guild_id: int) -> dict:
        async def op() -> dict:
            guild, error = self._guild(guild_id)
            if error:
                return error
            roles = [{
                "id": role.id,
                "name": role.name,
                "position": role.position,
                "managed": role.managed,
                "mentionable": role.mentionable,
            } for role in guild.roles]
            return {"success": True, "guild_id": guild.id, "roles": roles}
        return await self._run(op)

    async def _role_action(
        self,
        guild_id: int,
        user_id: int,
        role_id: int,
        reason: str,
        add: bool,
    ) -> dict:
        async def op() -> dict:
            guild, error = self._guild(guild_id)
            if error:
                return error
            member = guild.get_member(user_id) or await guild.fetch_member(user_id)
            role = guild.get_role(role_id)
            if role is None:
                return {"success": False, "message": f"Role {role_id} not found"}
            if add:
                await member.add_roles(role, reason=reason or "MCP admin action")
            else:
                await member.remove_roles(role, reason=reason or "MCP admin action")
            return {
                "success": True,
                "guild_id": guild.id,
                "user_id": member.id,
                "role_id": role.id,
            }
        return await self._run(op)

    async def add_role(
        self, guild_id: int, user_id: int, role_id: int, reason: str
    ) -> dict:
        return await self._role_action(guild_id, user_id, role_id, reason, True)

    async def remove_role(
        self, guild_id: int, user_id: int, role_id: int, reason: str
    ) -> dict:
        return await self._role_action(guild_id, user_id, role_id, reason, False)

    async def create_text_channel(
        self,
        guild_id: int,
        name: str,
        topic: str | None = None,
        category_id: int | None = None,
        reason: str = "",
    ) -> dict:
        async def op() -> dict:
            guild, error = self._guild(guild_id)
            if error:
                return error
            category = None
            if category_id is not None:
                category = guild.get_channel(category_id)
                if not isinstance(category, discord.CategoryChannel):
                    return {"success": False, "message": f"Category {category_id} not found"}
            channel = await guild.create_text_channel(
                name=name,
                topic=topic,
                category=category,
                reason=reason or "MCP admin action",
            )
            return {
                "success": True,
                "guild_id": guild.id,
                "channel_id": channel.id,
                "channel_name": channel.name,
            }
        return await self._run(op)

    async def update_text_channel(
        self,
        guild_id: int,
        channel_id: int,
        name: str | None = None,
        topic: str | None = None,
        slowmode_delay: int | None = None,
        reason: str = "",
    ) -> dict:
        async def op() -> dict:
            guild, error = self._guild(guild_id)
            if error:
                return error
            channel = guild.get_channel(channel_id)
            if not isinstance(channel, discord.TextChannel):
                return {"success": False, "message": f"Text channel {channel_id} not found"}
            kwargs = {"reason": reason or "MCP admin action"}
            if name is not None:
                kwargs["name"] = name
            if topic is not None:
                kwargs["topic"] = topic
            if slowmode_delay is not None:
                kwargs["slowmode_delay"] = max(0, min(slowmode_delay, 21_600))
            edited = await channel.edit(**kwargs)
            return {
                "success": True,
                "guild_id": guild.id,
                "channel_id": edited.id,
                "channel_name": edited.name,
            }
        return await self._run(op)

    async def delete_channel(self, guild_id: int, channel_id: int, reason: str) -> dict:
        async def op() -> dict:
            guild, error = self._guild(guild_id)
            if error:
                return error
            channel = self._channel(guild, channel_id)
            if channel is None:
                return {"success": False, "message": f"Channel {channel_id} not found"}
            channel_name = channel.name
            await channel.delete(reason=reason or "MCP admin action")
            return {
                "success": True,
                "guild_id": guild.id,
                "channel_id": channel_id,
                "channel_name": channel_name,
            }
        return await self._run(op)


discord_admin_service = DiscordAdminService()
