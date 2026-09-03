"""Extended guild-scoped Discord administration used by MCP.

This mixin keeps the public Discord admin surface semantic and typed while reusing
DiscordAdminService's guild allowlist, bot-loop bridge, and exception handling.
"""

from __future__ import annotations

import base64
import binascii
from io import BytesIO
from typing import Any

import discord


MAX_EMOJI_BYTES = 256 * 1024
MAX_STICKER_BYTES = 512 * 1024
DEFAULT_REASON = "MCP admin action"


class DiscordAdminExtensions:
    """Additional Discord administration operations for ``DiscordAdminService``."""

    @staticmethod
    def _reason(reason: str) -> str:
        return reason.strip() or DEFAULT_REASON

    @staticmethod
    def _decode_base64_payload(value: str, max_bytes: int) -> tuple[bytes | None, str | None]:
        raw = value.strip()
        if not raw:
            return None, "image data must not be empty"
        if raw.startswith("data:"):
            if "," not in raw:
                return None, "invalid data URI"
            raw = raw.split(",", 1)[1]
        try:
            decoded = base64.b64decode(raw, validate=True)
        except (ValueError, binascii.Error):
            return None, "image data is not valid base64"
        if not decoded:
            return None, "decoded image data must not be empty"
        if len(decoded) > max_bytes:
            return None, f"decoded image exceeds {max_bytes} bytes"
        return decoded, None

    @staticmethod
    def _permissions_from_names(names: list[str] | None) -> tuple[discord.Permissions | None, str | None]:
        if names is None:
            return None, None
        permissions = discord.Permissions.none()
        valid = set(discord.Permissions.VALID_FLAGS)
        unknown = sorted({name for name in names if name not in valid})
        if unknown:
            return None, f"unknown Discord permissions: {', '.join(unknown)}"
        for name in names:
            setattr(permissions, name, True)
        return permissions, None

    @staticmethod
    def _colour(value: int | None) -> tuple[discord.Colour | None, str | None]:
        if value is None:
            return None, None
        if not 0 <= value <= 0xFFFFFF:
            return None, "colour must be between 0x000000 and 0xFFFFFF"
        return discord.Colour(value), None

    @staticmethod
    def _enum_value(enum_type, value: str | None, aliases: dict[str, str] | None = None):
        if value is None:
            return None, None
        normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
        if aliases:
            normalized = aliases.get(normalized, normalized)
        enum_value = getattr(enum_type, normalized, None)
        if enum_value is None:
            allowed = [name for name in dir(enum_type) if not name.startswith("_")]
            return None, f"invalid {enum_type.__name__}: {value}; expected one of {', '.join(allowed)}"
        return enum_value, None

    async def _resolve_member(self, guild, user_id: int):
        return guild.get_member(user_id) or await guild.fetch_member(user_id)

    @staticmethod
    def _resolve_role(guild, role_id: int):
        return guild.get_role(role_id)

    @staticmethod
    def _resolve_channel(guild, channel_id: int):
        return guild.get_channel(channel_id) or guild.get_thread(channel_id)

    async def _resolve_webhook(self, guild, webhook_id: int):
        for webhook in await guild.webhooks():
            if webhook.id == webhook_id:
                return webhook
        return None

    async def _resolve_sticker(self, guild, sticker_id: int):
        get_sticker = getattr(guild, "get_sticker", None)
        if get_sticker:
            sticker = get_sticker(sticker_id)
            if sticker is not None:
                return sticker
        for sticker in getattr(guild, "stickers", []):
            if sticker.id == sticker_id:
                return sticker
        fetch_stickers = getattr(guild, "fetch_stickers", None)
        if fetch_stickers:
            for sticker in await fetch_stickers():
                if sticker.id == sticker_id:
                    return sticker
        return None

    # ------------------------------------------------------------------
    # Role management
    # ------------------------------------------------------------------

    async def create_role(
        self,
        guild_id: int,
        name: str,
        permissions: list[str] | None = None,
        colour: int | None = None,
        hoist: bool = False,
        mentionable: bool = False,
        reason: str = "",
    ) -> dict:
        name = name.strip()
        if not name or len(name) > 100:
            return {"success": False, "message": "role name must contain 1-100 characters"}
        permission_value, error = self._permissions_from_names(permissions)
        if error:
            return {"success": False, "message": error}
        colour_value, error = self._colour(colour)
        if error:
            return {"success": False, "message": error}

        async def op() -> dict:
            guild, guild_error = self._guild(guild_id)
            if guild_error:
                return guild_error
            kwargs: dict[str, Any] = {
                "name": name,
                "hoist": hoist,
                "mentionable": mentionable,
                "reason": self._reason(reason),
            }
            if permission_value is not None:
                kwargs["permissions"] = permission_value
            if colour_value is not None:
                kwargs["colour"] = colour_value
            role = await guild.create_role(**kwargs)
            return {
                "success": True,
                "guild_id": guild.id,
                "role": {"id": role.id, "name": role.name, "position": role.position},
            }

        return await self._run(op)

    async def update_role(
        self,
        guild_id: int,
        role_id: int,
        name: str | None = None,
        permissions: list[str] | None = None,
        colour: int | None = None,
        hoist: bool | None = None,
        mentionable: bool | None = None,
        position: int | None = None,
        reason: str = "",
    ) -> dict:
        permission_value, error = self._permissions_from_names(permissions)
        if error:
            return {"success": False, "message": error}
        colour_value, error = self._colour(colour)
        if error:
            return {"success": False, "message": error}
        if name is not None:
            name = name.strip()
            if not name or len(name) > 100:
                return {"success": False, "message": "role name must contain 1-100 characters"}
        if position is not None and position < 1:
            return {"success": False, "message": "role position must be at least 1"}

        async def op() -> dict:
            guild, guild_error = self._guild(guild_id)
            if guild_error:
                return guild_error
            role = self._resolve_role(guild, role_id)
            if role is None:
                return {"success": False, "message": f"Role {role_id} not found"}
            if role.is_default():
                return {"success": False, "message": "the @everyone role cannot be edited through this tool"}
            if role.managed:
                return {"success": False, "message": "managed integration roles cannot be edited"}
            kwargs: dict[str, Any] = {"reason": self._reason(reason)}
            if name is not None:
                kwargs["name"] = name
            if permission_value is not None:
                kwargs["permissions"] = permission_value
            if colour_value is not None:
                kwargs["colour"] = colour_value
            if hoist is not None:
                kwargs["hoist"] = hoist
            if mentionable is not None:
                kwargs["mentionable"] = mentionable
            if position is not None:
                kwargs["position"] = position
            if len(kwargs) == 1:
                return {"success": False, "message": "no role changes were provided"}
            edited = await role.edit(**kwargs)
            return {
                "success": True,
                "guild_id": guild.id,
                "role": {"id": edited.id, "name": edited.name, "position": edited.position},
            }

        return await self._run(op)

    async def delete_role(self, guild_id: int, role_id: int, reason: str = "") -> dict:
        async def op() -> dict:
            guild, guild_error = self._guild(guild_id)
            if guild_error:
                return guild_error
            role = self._resolve_role(guild, role_id)
            if role is None:
                return {"success": False, "message": f"Role {role_id} not found"}
            if role.is_default():
                return {"success": False, "message": "the @everyone role cannot be deleted"}
            if role.managed:
                return {"success": False, "message": "managed integration roles cannot be deleted"}
            role_name = role.name
            await role.delete(reason=self._reason(reason))
            return {"success": True, "guild_id": guild.id, "role_id": role_id, "role_name": role_name}

        return await self._run(op)

    # ------------------------------------------------------------------
    # Guild settings
    # ------------------------------------------------------------------

    async def get_guild_settings(self, guild_id: int) -> dict:
        async def op() -> dict:
            guild, guild_error = self._guild(guild_id)
            if guild_error:
                return guild_error
            return {
                "success": True,
                "guild_id": guild.id,
                "settings": {
                    "name": guild.name,
                    "description": getattr(guild, "description", None),
                    "verification_level": getattr(guild.verification_level, "name", str(guild.verification_level)),
                    "default_notifications": getattr(guild.default_notifications, "name", str(guild.default_notifications)),
                    "explicit_content_filter": getattr(guild.explicit_content_filter, "name", str(guild.explicit_content_filter)),
                    "afk_channel_id": getattr(getattr(guild, "afk_channel", None), "id", None),
                    "afk_timeout": getattr(guild, "afk_timeout", None),
                    "system_channel_id": getattr(getattr(guild, "system_channel", None), "id", None),
                },
            }

        return await self._run(op)

    async def update_guild_settings(
        self,
        guild_id: int,
        name: str | None = None,
        description: str | None = None,
        verification_level: str | None = None,
        default_notifications: str | None = None,
        explicit_content_filter: str | None = None,
        afk_channel_id: int | None = None,
        clear_afk_channel: bool = False,
        afk_timeout: int | None = None,
        system_channel_id: int | None = None,
        clear_system_channel: bool = False,
        reason: str = "",
    ) -> dict:
        if name is not None:
            name = name.strip()
            if not 2 <= len(name) <= 100:
                return {"success": False, "message": "guild name must contain 2-100 characters"}
        if description is not None and len(description) > 120:
            return {"success": False, "message": "guild description must be at most 120 characters"}
        if afk_timeout is not None and afk_timeout not in {60, 300, 900, 1800, 3600}:
            return {"success": False, "message": "afk_timeout must be one of 60, 300, 900, 1800, or 3600"}
        verification, error = self._enum_value(discord.VerificationLevel, verification_level)
        if error:
            return {"success": False, "message": error}
        notifications, error = self._enum_value(
            discord.NotificationLevel,
            default_notifications,
            {"all": "all_messages", "mentions": "only_mentions"},
        )
        if error:
            return {"success": False, "message": error}
        content_filter, error = self._enum_value(
            discord.ContentFilter,
            explicit_content_filter,
            {"none": "disabled", "members_without_roles": "no_role", "all": "all_members"},
        )
        if error:
            return {"success": False, "message": error}

        async def op() -> dict:
            guild, guild_error = self._guild(guild_id)
            if guild_error:
                return guild_error
            kwargs: dict[str, Any] = {"reason": self._reason(reason)}
            if name is not None:
                kwargs["name"] = name
            if description is not None:
                kwargs["description"] = description
            if verification is not None:
                kwargs["verification_level"] = verification
            if notifications is not None:
                kwargs["default_notifications"] = notifications
            if content_filter is not None:
                kwargs["explicit_content_filter"] = content_filter
            if afk_timeout is not None:
                kwargs["afk_timeout"] = afk_timeout
            if afk_channel_id is not None and clear_afk_channel:
                return {"success": False, "message": "cannot set and clear the AFK channel in one request"}
            if system_channel_id is not None and clear_system_channel:
                return {"success": False, "message": "cannot set and clear the system channel in one request"}
            if clear_afk_channel:
                kwargs["afk_channel"] = None
            elif afk_channel_id is not None:
                channel = guild.get_channel(afk_channel_id)
                if channel is None:
                    return {"success": False, "message": f"AFK channel {afk_channel_id} not found"}
                kwargs["afk_channel"] = channel
            if clear_system_channel:
                kwargs["system_channel"] = None
            elif system_channel_id is not None:
                channel = guild.get_channel(system_channel_id)
                if channel is None:
                    return {"success": False, "message": f"system channel {system_channel_id} not found"}
                kwargs["system_channel"] = channel
            if len(kwargs) == 1:
                return {"success": False, "message": "no guild setting changes were provided"}
            edited = await guild.edit(**kwargs)
            return {"success": True, "guild_id": guild.id, "guild_name": edited.name}

        return await self._run(op)

    # ------------------------------------------------------------------
    # Channel permission overwrites and ordering
    # ------------------------------------------------------------------

    async def list_channel_permissions(self, guild_id: int, channel_id: int) -> dict:
        async def op() -> dict:
            guild, guild_error = self._guild(guild_id)
            if guild_error:
                return guild_error
            channel = self._resolve_channel(guild, channel_id)
            if channel is None or not hasattr(channel, "overwrites"):
                return {"success": False, "message": f"Channel {channel_id} not found or has no permission overwrites"}
            entries = []
            for target, overwrite in channel.overwrites.items():
                values = {}
                for permission in discord.Permissions.VALID_FLAGS:
                    value = getattr(overwrite, permission, None)
                    if value is not None:
                        values[permission] = value
                target_type = "role" if isinstance(target, discord.Role) else "member"
                entries.append(
                    {
                        "target_type": target_type,
                        "target_id": target.id,
                        "target_name": getattr(target, "name", getattr(target, "display_name", str(target))),
                        "permissions": values,
                    }
                )
            return {"success": True, "guild_id": guild.id, "channel_id": channel_id, "overwrites": entries}

        return await self._run(op)

    async def set_channel_permissions(
        self,
        guild_id: int,
        channel_id: int,
        target_type: str,
        target_id: int,
        permissions: dict[str, bool | None],
        reason: str = "",
    ) -> dict:
        normalized_type = target_type.strip().lower()
        if normalized_type not in {"role", "member"}:
            return {"success": False, "message": "target_type must be 'role' or 'member'"}
        valid = set(discord.Permissions.VALID_FLAGS)
        unknown = sorted(set(permissions) - valid)
        if unknown:
            return {"success": False, "message": f"unknown Discord permissions: {', '.join(unknown)}"}
        if not permissions:
            return {"success": False, "message": "at least one permission overwrite must be provided"}

        async def op() -> dict:
            guild, guild_error = self._guild(guild_id)
            if guild_error:
                return guild_error
            channel = self._resolve_channel(guild, channel_id)
            if channel is None or not hasattr(channel, "set_permissions"):
                return {"success": False, "message": f"Channel {channel_id} not found or does not support overwrites"}
            if normalized_type == "role":
                target = self._resolve_role(guild, target_id)
                if target is None:
                    return {"success": False, "message": f"Role {target_id} not found"}
            else:
                target = await self._resolve_member(guild, target_id)
            overwrite = discord.PermissionOverwrite(**permissions)
            await channel.set_permissions(target, overwrite=overwrite, reason=self._reason(reason))
            return {
                "success": True,
                "guild_id": guild.id,
                "channel_id": channel_id,
                "target_type": normalized_type,
                "target_id": target_id,
                "permissions": permissions,
            }

        return await self._run(op)

    async def clear_channel_permissions(
        self,
        guild_id: int,
        channel_id: int,
        target_type: str,
        target_id: int,
        reason: str = "",
    ) -> dict:
        normalized_type = target_type.strip().lower()
        if normalized_type not in {"role", "member"}:
            return {"success": False, "message": "target_type must be 'role' or 'member'"}

        async def op() -> dict:
            guild, guild_error = self._guild(guild_id)
            if guild_error:
                return guild_error
            channel = self._resolve_channel(guild, channel_id)
            if channel is None or not hasattr(channel, "set_permissions"):
                return {"success": False, "message": f"Channel {channel_id} not found or does not support overwrites"}
            if normalized_type == "role":
                target = self._resolve_role(guild, target_id)
                if target is None:
                    return {"success": False, "message": f"Role {target_id} not found"}
            else:
                target = await self._resolve_member(guild, target_id)
            await channel.set_permissions(target, overwrite=None, reason=self._reason(reason))
            return {"success": True, "guild_id": guild.id, "channel_id": channel_id, "target_id": target_id}

        return await self._run(op)

    async def move_channel(
        self,
        guild_id: int,
        channel_id: int,
        position: int | None = None,
        category_id: int | None = None,
        clear_category: bool = False,
        sync_permissions: bool | None = None,
        reason: str = "",
    ) -> dict:
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
                kwargs["sync_permissions"] = sync_permissions
            if len(kwargs) == 1:
                return {"success": False, "message": "no channel move/order changes were provided"}
            edited = await channel.edit(**kwargs)
            return {
                "success": True,
                "guild_id": guild.id,
                "channel_id": edited.id,
                "position": getattr(edited, "position", None),
                "category_id": getattr(edited, "category_id", None),
            }

        return await self._run(op)

    # ------------------------------------------------------------------
    # Webhooks
    # ------------------------------------------------------------------

    async def list_webhooks(self, guild_id: int) -> dict:
        async def op() -> dict:
            guild, guild_error = self._guild(guild_id)
            if guild_error:
                return guild_error
            hooks = await guild.webhooks()
            return {
                "success": True,
                "guild_id": guild.id,
                "webhooks": [
                    {
                        "id": hook.id,
                        "name": hook.name,
                        "channel_id": hook.channel_id,
                        "type": str(hook.type),
                        "user_id": getattr(getattr(hook, "user", None), "id", None),
                        "application_id": getattr(hook, "application_id", None),
                    }
                    for hook in hooks
                ],
            }

        return await self._run(op)

    async def create_webhook(self, guild_id: int, channel_id: int, name: str, reason: str = "") -> dict:
        name = name.strip()
        if not 1 <= len(name) <= 80:
            return {"success": False, "message": "webhook name must contain 1-80 characters"}

        async def op() -> dict:
            guild, guild_error = self._guild(guild_id)
            if guild_error:
                return guild_error
            channel = self._resolve_channel(guild, channel_id)
            if channel is None or not hasattr(channel, "create_webhook"):
                return {"success": False, "message": f"Channel {channel_id} does not support webhooks"}
            hook = await channel.create_webhook(name=name, reason=self._reason(reason))
            return {"success": True, "guild_id": guild.id, "webhook_id": hook.id, "name": hook.name, "channel_id": hook.channel_id}

        return await self._run(op)

    async def update_webhook(
        self,
        guild_id: int,
        webhook_id: int,
        name: str | None = None,
        channel_id: int | None = None,
        reason: str = "",
    ) -> dict:
        if name is not None:
            name = name.strip()
            if not 1 <= len(name) <= 80:
                return {"success": False, "message": "webhook name must contain 1-80 characters"}

        async def op() -> dict:
            guild, guild_error = self._guild(guild_id)
            if guild_error:
                return guild_error
            hook = await self._resolve_webhook(guild, webhook_id)
            if hook is None:
                return {"success": False, "message": f"Webhook {webhook_id} not found in guild {guild_id}"}
            kwargs: dict[str, Any] = {"reason": self._reason(reason)}
            if name is not None:
                kwargs["name"] = name
            if channel_id is not None:
                channel = self._resolve_channel(guild, channel_id)
                if channel is None or not hasattr(channel, "create_webhook"):
                    return {"success": False, "message": f"Channel {channel_id} does not support webhooks"}
                kwargs["channel"] = channel
            if len(kwargs) == 1:
                return {"success": False, "message": "no webhook changes were provided"}
            edited = await hook.edit(**kwargs)
            return {"success": True, "guild_id": guild.id, "webhook_id": edited.id, "name": edited.name, "channel_id": edited.channel_id}

        return await self._run(op)

    async def delete_webhook(self, guild_id: int, webhook_id: int, reason: str = "") -> dict:
        async def op() -> dict:
            guild, guild_error = self._guild(guild_id)
            if guild_error:
                return guild_error
            hook = await self._resolve_webhook(guild, webhook_id)
            if hook is None:
                return {"success": False, "message": f"Webhook {webhook_id} not found in guild {guild_id}"}
            await hook.delete(reason=self._reason(reason))
            return {"success": True, "guild_id": guild.id, "webhook_id": webhook_id}

        return await self._run(op)

    # ------------------------------------------------------------------
    # Emoji and sticker management
    # ------------------------------------------------------------------

    async def list_emojis(self, guild_id: int) -> dict:
        async def op() -> dict:
            guild, guild_error = self._guild(guild_id)
            if guild_error:
                return guild_error
            return {
                "success": True,
                "guild_id": guild.id,
                "emojis": [
                    {
                        "id": emoji.id,
                        "name": emoji.name,
                        "animated": emoji.animated,
                        "available": emoji.available,
                        "managed": emoji.managed,
                        "role_ids": [role.id for role in emoji.roles],
                    }
                    for emoji in guild.emojis
                ],
            }

        return await self._run(op)

    async def create_emoji(self, guild_id: int, name: str, image_base64: str, reason: str = "") -> dict:
        name = name.strip()
        if not 2 <= len(name) <= 32:
            return {"success": False, "message": "emoji name must contain 2-32 characters"}
        image, error = self._decode_base64_payload(image_base64, MAX_EMOJI_BYTES)
        if error:
            return {"success": False, "message": error}

        async def op() -> dict:
            guild, guild_error = self._guild(guild_id)
            if guild_error:
                return guild_error
            emoji = await guild.create_custom_emoji(name=name, image=image, reason=self._reason(reason))
            return {"success": True, "guild_id": guild.id, "emoji_id": emoji.id, "name": emoji.name}

        return await self._run(op)

    async def update_emoji(
        self,
        guild_id: int,
        emoji_id: int,
        name: str | None = None,
        role_ids: list[int] | None = None,
        reason: str = "",
    ) -> dict:
        if name is not None:
            name = name.strip()
            if not 2 <= len(name) <= 32:
                return {"success": False, "message": "emoji name must contain 2-32 characters"}

        async def op() -> dict:
            guild, guild_error = self._guild(guild_id)
            if guild_error:
                return guild_error
            emoji = guild.get_emoji(emoji_id)
            if emoji is None:
                return {"success": False, "message": f"Emoji {emoji_id} not found"}
            kwargs: dict[str, Any] = {"reason": self._reason(reason)}
            if name is not None:
                kwargs["name"] = name
            if role_ids is not None:
                roles = []
                for role_id in role_ids:
                    role = guild.get_role(role_id)
                    if role is None:
                        return {"success": False, "message": f"Role {role_id} not found"}
                    roles.append(role)
                kwargs["roles"] = roles
            if len(kwargs) == 1:
                return {"success": False, "message": "no emoji changes were provided"}
            edited = await emoji.edit(**kwargs)
            return {"success": True, "guild_id": guild.id, "emoji_id": edited.id, "name": edited.name}

        return await self._run(op)

    async def delete_emoji(self, guild_id: int, emoji_id: int, reason: str = "") -> dict:
        async def op() -> dict:
            guild, guild_error = self._guild(guild_id)
            if guild_error:
                return guild_error
            emoji = guild.get_emoji(emoji_id)
            if emoji is None:
                return {"success": False, "message": f"Emoji {emoji_id} not found"}
            await emoji.delete(reason=self._reason(reason))
            return {"success": True, "guild_id": guild.id, "emoji_id": emoji_id}

        return await self._run(op)

    async def list_stickers(self, guild_id: int) -> dict:
        async def op() -> dict:
            guild, guild_error = self._guild(guild_id)
            if guild_error:
                return guild_error
            stickers = list(getattr(guild, "stickers", []))
            if not stickers and hasattr(guild, "fetch_stickers"):
                stickers = list(await guild.fetch_stickers())
            return {
                "success": True,
                "guild_id": guild.id,
                "stickers": [
                    {
                        "id": sticker.id,
                        "name": sticker.name,
                        "description": sticker.description,
                        "emoji": getattr(sticker, "emoji", None),
                        "available": getattr(sticker, "available", None),
                        "format": str(getattr(sticker, "format", "")),
                    }
                    for sticker in stickers
                ],
            }

        return await self._run(op)

    async def create_sticker(
        self,
        guild_id: int,
        name: str,
        description: str,
        emoji: str,
        image_base64: str,
        filename: str = "sticker.png",
        reason: str = "",
    ) -> dict:
        name = name.strip()
        description = description.strip()
        emoji = emoji.strip()
        filename = filename.strip() or "sticker.png"
        if not 2 <= len(name) <= 30:
            return {"success": False, "message": "sticker name must contain 2-30 characters"}
        if not 2 <= len(description) <= 100:
            return {"success": False, "message": "sticker description must contain 2-100 characters"}
        if not emoji:
            return {"success": False, "message": "sticker emoji tag must not be empty"}
        if not filename.lower().endswith((".png", ".apng", ".json")):
            return {"success": False, "message": "sticker filename must end in .png, .apng, or .json"}
        image, error = self._decode_base64_payload(image_base64, MAX_STICKER_BYTES)
        if error:
            return {"success": False, "message": error}

        async def op() -> dict:
            guild, guild_error = self._guild(guild_id)
            if guild_error:
                return guild_error
            file = discord.File(BytesIO(image), filename=filename)
            sticker = await guild.create_sticker(
                name=name,
                description=description,
                emoji=emoji,
                file=file,
                reason=self._reason(reason),
            )
            return {"success": True, "guild_id": guild.id, "sticker_id": sticker.id, "name": sticker.name}

        return await self._run(op)

    async def update_sticker(
        self,
        guild_id: int,
        sticker_id: int,
        name: str | None = None,
        description: str | None = None,
        emoji: str | None = None,
        reason: str = "",
    ) -> dict:
        if name is not None:
            name = name.strip()
            if not 2 <= len(name) <= 30:
                return {"success": False, "message": "sticker name must contain 2-30 characters"}
        if description is not None:
            description = description.strip()
            if not 2 <= len(description) <= 100:
                return {"success": False, "message": "sticker description must contain 2-100 characters"}
        if emoji is not None:
            emoji = emoji.strip()
            if not emoji:
                return {"success": False, "message": "sticker emoji tag must not be empty"}

        async def op() -> dict:
            guild, guild_error = self._guild(guild_id)
            if guild_error:
                return guild_error
            sticker = await self._resolve_sticker(guild, sticker_id)
            if sticker is None:
                return {"success": False, "message": f"Sticker {sticker_id} not found"}
            kwargs: dict[str, Any] = {"reason": self._reason(reason)}
            if name is not None:
                kwargs["name"] = name
            if description is not None:
                kwargs["description"] = description
            if emoji is not None:
                kwargs["emoji"] = emoji
            if len(kwargs) == 1:
                return {"success": False, "message": "no sticker changes were provided"}
            edited = await sticker.edit(**kwargs)
            return {"success": True, "guild_id": guild.id, "sticker_id": edited.id, "name": edited.name}

        return await self._run(op)

    async def delete_sticker(self, guild_id: int, sticker_id: int, reason: str = "") -> dict:
        async def op() -> dict:
            guild, guild_error = self._guild(guild_id)
            if guild_error:
                return guild_error
            sticker = await self._resolve_sticker(guild, sticker_id)
            if sticker is None:
                return {"success": False, "message": f"Sticker {sticker_id} not found"}
            await sticker.delete(reason=self._reason(reason))
            return {"success": True, "guild_id": guild.id, "sticker_id": sticker_id}

        return await self._run(op)

    # ------------------------------------------------------------------
    # Member nickname and voice administration
    # ------------------------------------------------------------------

    async def set_member_nickname(
        self,
        guild_id: int,
        user_id: int,
        nickname: str | None,
        reason: str = "",
    ) -> dict:
        if nickname is not None:
            nickname = nickname.strip()
            if len(nickname) > 32:
                return {"success": False, "message": "nickname must be at most 32 characters"}
            if not nickname:
                nickname = None

        async def op() -> dict:
            guild, guild_error = self._guild(guild_id)
            if guild_error:
                return guild_error
            member = await self._resolve_member(guild, user_id)
            edited = await member.edit(nick=nickname, reason=self._reason(reason))
            return {
                "success": True,
                "guild_id": guild.id,
                "user_id": member.id,
                "nickname": getattr(edited, "nick", nickname),
            }

        return await self._run(op)

    async def move_member_voice(
        self,
        guild_id: int,
        user_id: int,
        channel_id: int | None,
        reason: str = "",
    ) -> dict:
        async def op() -> dict:
            guild, guild_error = self._guild(guild_id)
            if guild_error:
                return guild_error
            member = await self._resolve_member(guild, user_id)
            channel = None
            if channel_id is not None:
                channel = guild.get_channel(channel_id)
                if not isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
                    return {"success": False, "message": f"Voice/stage channel {channel_id} not found"}
            await member.move_to(channel, reason=self._reason(reason))
            return {"success": True, "guild_id": guild.id, "user_id": member.id, "channel_id": channel_id}

        return await self._run(op)

    async def set_member_voice_state(
        self,
        guild_id: int,
        user_id: int,
        mute: bool | None = None,
        deafen: bool | None = None,
        reason: str = "",
    ) -> dict:
        if mute is None and deafen is None:
            return {"success": False, "message": "at least one of mute or deafen must be provided"}

        async def op() -> dict:
            guild, guild_error = self._guild(guild_id)
            if guild_error:
                return guild_error
            member = await self._resolve_member(guild, user_id)
            kwargs: dict[str, Any] = {"reason": self._reason(reason)}
            if mute is not None:
                kwargs["mute"] = mute
            if deafen is not None:
                kwargs["deafen"] = deafen
            await member.edit(**kwargs)
            return {"success": True, "guild_id": guild.id, "user_id": member.id, "mute": mute, "deafen": deafen}

        return await self._run(op)

    # ------------------------------------------------------------------
    # Invites
    # ------------------------------------------------------------------

    async def list_invites(self, guild_id: int) -> dict:
        async def op() -> dict:
            guild, guild_error = self._guild(guild_id)
            if guild_error:
                return guild_error
            invites = await guild.invites()
            return {
                "success": True,
                "guild_id": guild.id,
                "invites": [
                    {
                        "code": invite.code,
                        "channel_id": getattr(getattr(invite, "channel", None), "id", None),
                        "inviter_id": getattr(getattr(invite, "inviter", None), "id", None),
                        "max_age": invite.max_age,
                        "max_uses": invite.max_uses,
                        "uses": invite.uses,
                        "temporary": invite.temporary,
                        "expires_at": invite.expires_at.isoformat() if getattr(invite, "expires_at", None) else None,
                    }
                    for invite in invites
                ],
            }

        return await self._run(op)

    async def create_invite(
        self,
        guild_id: int,
        channel_id: int,
        max_age: int = 0,
        max_uses: int = 0,
        temporary: bool = False,
        unique: bool = True,
        reason: str = "",
    ) -> dict:
        if not 0 <= max_age <= 604_800:
            return {"success": False, "message": "max_age must be between 0 and 604800 seconds"}
        if not 0 <= max_uses <= 100:
            return {"success": False, "message": "max_uses must be between 0 and 100"}

        async def op() -> dict:
            guild, guild_error = self._guild(guild_id)
            if guild_error:
                return guild_error
            channel = guild.get_channel(channel_id)
            if channel is None or not hasattr(channel, "create_invite"):
                return {"success": False, "message": f"Channel {channel_id} does not support invites"}
            invite = await channel.create_invite(
                max_age=max_age,
                max_uses=max_uses,
                temporary=temporary,
                unique=unique,
                reason=self._reason(reason),
            )
            return {"success": True, "guild_id": guild.id, "channel_id": channel_id, "code": invite.code}

        return await self._run(op)

    async def delete_invite(self, guild_id: int, code: str, reason: str = "") -> dict:
        code = code.strip()
        if not code:
            return {"success": False, "message": "invite code must not be empty"}

        async def op() -> dict:
            guild, guild_error = self._guild(guild_id)
            if guild_error:
                return guild_error
            invite = next((item for item in await guild.invites() if item.code == code), None)
            if invite is None:
                return {"success": False, "message": f"Invite {code} not found in guild {guild_id}"}
            await invite.delete(reason=self._reason(reason))
            return {"success": True, "guild_id": guild.id, "code": code}

        return await self._run(op)

    # ------------------------------------------------------------------
    # Threads
    # ------------------------------------------------------------------

    async def list_threads(self, guild_id: int) -> dict:
        async def op() -> dict:
            guild, guild_error = self._guild(guild_id)
            if guild_error:
                return guild_error
            threads = list(getattr(guild, "threads", []))
            return {
                "success": True,
                "guild_id": guild.id,
                "threads": [
                    {
                        "id": thread.id,
                        "name": thread.name,
                        "parent_id": thread.parent_id,
                        "owner_id": thread.owner_id,
                        "archived": thread.archived,
                        "locked": thread.locked,
                        "auto_archive_duration": thread.auto_archive_duration,
                        "slowmode_delay": thread.slowmode_delay,
                        "message_count": getattr(thread, "message_count", None),
                    }
                    for thread in threads
                ],
            }

        return await self._run(op)

    async def create_thread(
        self,
        guild_id: int,
        channel_id: int,
        name: str,
        auto_archive_duration: int = 1440,
        slowmode_delay: int = 0,
        reason: str = "",
    ) -> dict:
        name = name.strip()
        if not 1 <= len(name) <= 100:
            return {"success": False, "message": "thread name must contain 1-100 characters"}
        if auto_archive_duration not in {60, 1440, 4320, 10080}:
            return {"success": False, "message": "auto_archive_duration must be 60, 1440, 4320, or 10080 minutes"}
        if not 0 <= slowmode_delay <= 21_600:
            return {"success": False, "message": "slowmode_delay must be between 0 and 21600 seconds"}

        async def op() -> dict:
            guild, guild_error = self._guild(guild_id)
            if guild_error:
                return guild_error
            channel = guild.get_channel(channel_id)
            if channel is None or not hasattr(channel, "create_thread"):
                return {"success": False, "message": f"Channel {channel_id} does not support threads"}
            thread = await channel.create_thread(
                name=name,
                auto_archive_duration=auto_archive_duration,
                slowmode_delay=slowmode_delay,
                reason=self._reason(reason),
            )
            return {"success": True, "guild_id": guild.id, "thread_id": thread.id, "name": thread.name, "parent_id": thread.parent_id}

        return await self._run(op)

    async def update_thread(
        self,
        guild_id: int,
        thread_id: int,
        name: str | None = None,
        archived: bool | None = None,
        locked: bool | None = None,
        auto_archive_duration: int | None = None,
        slowmode_delay: int | None = None,
        reason: str = "",
    ) -> dict:
        if name is not None:
            name = name.strip()
            if not 1 <= len(name) <= 100:
                return {"success": False, "message": "thread name must contain 1-100 characters"}
        if auto_archive_duration is not None and auto_archive_duration not in {60, 1440, 4320, 10080}:
            return {"success": False, "message": "auto_archive_duration must be 60, 1440, 4320, or 10080 minutes"}
        if slowmode_delay is not None and not 0 <= slowmode_delay <= 21_600:
            return {"success": False, "message": "slowmode_delay must be between 0 and 21600 seconds"}

        async def op() -> dict:
            guild, guild_error = self._guild(guild_id)
            if guild_error:
                return guild_error
            thread = guild.get_thread(thread_id)
            if thread is None:
                return {"success": False, "message": f"Thread {thread_id} not found"}
            kwargs: dict[str, Any] = {"reason": self._reason(reason)}
            if name is not None:
                kwargs["name"] = name
            if archived is not None:
                kwargs["archived"] = archived
            if locked is not None:
                kwargs["locked"] = locked
            if auto_archive_duration is not None:
                kwargs["auto_archive_duration"] = auto_archive_duration
            if slowmode_delay is not None:
                kwargs["slowmode_delay"] = slowmode_delay
            if len(kwargs) == 1:
                return {"success": False, "message": "no thread changes were provided"}
            edited = await thread.edit(**kwargs)
            return {"success": True, "guild_id": guild.id, "thread_id": edited.id, "name": edited.name, "archived": edited.archived, "locked": edited.locked}

        return await self._run(op)

    async def delete_thread(self, guild_id: int, thread_id: int, reason: str = "") -> dict:
        async def op() -> dict:
            guild, guild_error = self._guild(guild_id)
            if guild_error:
                return guild_error
            thread = guild.get_thread(thread_id)
            if thread is None:
                return {"success": False, "message": f"Thread {thread_id} not found"}
            thread_name = thread.name
            await thread.delete(reason=self._reason(reason))
            return {"success": True, "guild_id": guild.id, "thread_id": thread_id, "thread_name": thread_name}

        return await self._run(op)

    # ------------------------------------------------------------------
    # Message pinning and moderation cleanup
    # ------------------------------------------------------------------

    async def pin_message(self, guild_id: int, channel_id: int, message_id: int, reason: str = "") -> dict:
        async def op() -> dict:
            guild, guild_error = self._guild(guild_id)
            if guild_error:
                return guild_error
            channel = self._resolve_channel(guild, channel_id)
            if channel is None or not hasattr(channel, "fetch_message"):
                return {"success": False, "message": f"Text channel/thread {channel_id} not found"}
            message = await channel.fetch_message(message_id)
            await message.pin(reason=self._reason(reason))
            return {"success": True, "guild_id": guild.id, "channel_id": channel_id, "message_id": message_id, "pinned": True}

        return await self._run(op)

    async def unpin_message(self, guild_id: int, channel_id: int, message_id: int, reason: str = "") -> dict:
        async def op() -> dict:
            guild, guild_error = self._guild(guild_id)
            if guild_error:
                return guild_error
            channel = self._resolve_channel(guild, channel_id)
            if channel is None or not hasattr(channel, "fetch_message"):
                return {"success": False, "message": f"Text channel/thread {channel_id} not found"}
            message = await channel.fetch_message(message_id)
            await message.unpin(reason=self._reason(reason))
            return {"success": True, "guild_id": guild.id, "channel_id": channel_id, "message_id": message_id, "pinned": False}

        return await self._run(op)

    async def purge_messages(
        self,
        guild_id: int,
        channel_id: int,
        limit: int,
        user_id: int | None = None,
        contains: str | None = None,
        reason: str = "",
    ) -> dict:
        if not 1 <= limit <= 100:
            return {"success": False, "message": "purge limit must be between 1 and 100"}
        if contains is not None:
            contains = contains.strip()
            if not contains:
                contains = None

        async def op() -> dict:
            guild, guild_error = self._guild(guild_id)
            if guild_error:
                return guild_error
            channel = guild.get_channel(channel_id)
            if channel is None or not hasattr(channel, "purge"):
                return {"success": False, "message": f"Channel {channel_id} does not support message purge"}

            def check(message) -> bool:
                if user_id is not None and message.author.id != user_id:
                    return False
                if contains is not None and contains not in message.content:
                    return False
                return True

            filtered = user_id is not None or contains is not None
            deleted = await channel.purge(
                limit=limit,
                check=check if filtered else None,
                reason=self._reason(reason),
                bulk=True,
            )
            return {
                "success": True,
                "guild_id": guild.id,
                "channel_id": channel_id,
                "scanned_limit": limit,
                "deleted_count": len(deleted),
                "deleted_message_ids": [message.id for message in deleted],
            }

        return await self._run(op)
