"""Registration for the extended semantic Discord MCP tool surface."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field


EXTENDED_TOOL_NAMES = {
    "discord_create_role",
    "discord_update_role",
    "discord_delete_role",
    "discord_get_guild_settings",
    "discord_update_guild_settings",
    "discord_list_channel_permissions",
    "discord_set_channel_permissions",
    "discord_clear_channel_permissions",
    "discord_update_channel",
    "discord_move_channel",
    "discord_list_webhooks",
    "discord_create_webhook",
    "discord_update_webhook",
    "discord_delete_webhook",
    "discord_list_emojis",
    "discord_create_emoji",
    "discord_update_emoji",
    "discord_delete_emoji",
    "discord_list_stickers",
    "discord_create_sticker",
    "discord_update_sticker",
    "discord_delete_sticker",
    "discord_set_member_nickname",
    "discord_move_member_voice",
    "discord_set_member_voice_state",
    "discord_list_invites",
    "discord_create_invite",
    "discord_delete_invite",
    "discord_list_threads",
    "discord_create_thread",
    "discord_update_thread",
    "discord_delete_thread",
    "discord_pin_message",
    "discord_unpin_message",
    "discord_purge_messages",
}


def register_extended_tools(server, service, read_only, write, destructive) -> set[str]:
    """Register all extended Discord admin tools on an MCP-compatible server."""

    @server.tool(title="Create Discord role", annotations=write)
    async def discord_create_role(
        guild_id: Annotated[int, Field(description="Discord guild/server ID")],
        name: Annotated[str, Field(min_length=1, max_length=100)],
        permissions: Annotated[list[str] | None, Field(description="Discord permission flag names to enable")] = None,
        colour: Annotated[int | None, Field(ge=0, le=0xFFFFFF, description="RGB role colour as integer")] = None,
        hoist: bool = False,
        mentionable: bool = False,
        reason: Annotated[str, Field(max_length=512)] = "MCP admin action",
    ) -> dict:
        return await service.create_role(guild_id, name, permissions, colour, hoist, mentionable, reason)

    @server.tool(title="Update Discord role", annotations=write)
    async def discord_update_role(
        guild_id: Annotated[int, Field(description="Discord guild/server ID")],
        role_id: Annotated[int, Field(description="Discord role ID")],
        name: Annotated[str | None, Field(min_length=1, max_length=100)] = None,
        permissions: Annotated[list[str] | None, Field(description="Complete set of Discord permission flag names to enable")] = None,
        colour: Annotated[int | None, Field(ge=0, le=0xFFFFFF)] = None,
        hoist: bool | None = None,
        mentionable: bool | None = None,
        position: Annotated[int | None, Field(ge=1)] = None,
        reason: Annotated[str, Field(max_length=512)] = "MCP admin action",
    ) -> dict:
        return await service.update_role(guild_id, role_id, name, permissions, colour, hoist, mentionable, position, reason)

    @server.tool(title="Delete Discord role", annotations=destructive)
    async def discord_delete_role(
        guild_id: Annotated[int, Field(description="Discord guild/server ID")],
        role_id: Annotated[int, Field(description="Discord role ID")],
        reason: Annotated[str, Field(max_length=512)] = "MCP admin action",
    ) -> dict:
        return await service.delete_role(guild_id, role_id, reason)

    @server.tool(title="Get Discord server settings", annotations=read_only)
    async def discord_get_guild_settings(
        guild_id: Annotated[int, Field(description="Discord guild/server ID")],
    ) -> dict:
        return await service.get_guild_settings(guild_id)

    @server.tool(title="Update Discord server settings", annotations=write)
    async def discord_update_guild_settings(
        guild_id: Annotated[int, Field(description="Discord guild/server ID")],
        name: Annotated[str | None, Field(min_length=2, max_length=100)] = None,
        description: Annotated[str | None, Field(max_length=120)] = None,
        verification_level: Annotated[str | None, Field(description="none, low, medium, high, or highest")] = None,
        default_notifications: Annotated[str | None, Field(description="all_messages/all or only_mentions/mentions")] = None,
        explicit_content_filter: Annotated[str | None, Field(description="disabled/none, no_role/members_without_roles, or all_members/all")] = None,
        afk_channel_id: int | None = None,
        clear_afk_channel: bool = False,
        afk_timeout: Annotated[int | None, Field(description="60, 300, 900, 1800, or 3600 seconds")] = None,
        system_channel_id: int | None = None,
        clear_system_channel: bool = False,
        reason: Annotated[str, Field(max_length=512)] = "MCP admin action",
    ) -> dict:
        return await service.update_guild_settings(
            guild_id,
            name,
            description,
            verification_level,
            default_notifications,
            explicit_content_filter,
            afk_channel_id,
            clear_afk_channel,
            afk_timeout,
            system_channel_id,
            clear_system_channel,
            reason,
        )

    @server.tool(title="List Discord channel permission overwrites", annotations=read_only)
    async def discord_list_channel_permissions(
        guild_id: Annotated[int, Field(description="Discord guild/server ID")],
        channel_id: Annotated[int, Field(description="Discord channel ID")],
    ) -> dict:
        return await service.list_channel_permissions(guild_id, channel_id)

    @server.tool(title="Set Discord channel permission overwrite", annotations=write)
    async def discord_set_channel_permissions(
        guild_id: Annotated[int, Field(description="Discord guild/server ID")],
        channel_id: Annotated[int, Field(description="Discord channel ID")],
        target_type: Annotated[str, Field(description="role or member")],
        target_id: Annotated[int, Field(description="Discord role or member ID")],
        permissions: Annotated[dict[str, bool | None], Field(description="Permission names mapped to allow=true, deny=false, or inherit=null")],
        reason: Annotated[str, Field(max_length=512)] = "MCP admin action",
    ) -> dict:
        return await service.set_channel_permissions(guild_id, channel_id, target_type, target_id, permissions, reason)

    @server.tool(title="Clear Discord channel permission overwrite", annotations=destructive)
    async def discord_clear_channel_permissions(
        guild_id: Annotated[int, Field(description="Discord guild/server ID")],
        channel_id: Annotated[int, Field(description="Discord channel ID")],
        target_type: Annotated[str, Field(description="role or member")],
        target_id: Annotated[int, Field(description="Discord role or member ID")],
        reason: Annotated[str, Field(max_length=512)] = "MCP admin action",
    ) -> dict:
        return await service.clear_channel_permissions(guild_id, channel_id, target_type, target_id, reason)

    @server.tool(title="Rename Discord guild channel", annotations=write)
    async def discord_update_channel(
        guild_id: Annotated[int, Field(description="Discord guild/server ID")],
        channel_id: Annotated[int, Field(description="Discord guild channel ID")],
        name: Annotated[str, Field(min_length=1, max_length=100, description="New channel/category name")],
        reason: Annotated[str, Field(max_length=512)] = "MCP admin action",
    ) -> dict:
        return await service.update_channel(guild_id, channel_id, name, reason)

    @server.tool(title="Move/reorder Discord channel", annotations=write)
    async def discord_move_channel(
        guild_id: Annotated[int, Field(description="Discord guild/server ID")],
        channel_id: Annotated[int, Field(description="Discord guild channel ID")],
        position: Annotated[int | None, Field(ge=0)] = None,
        category_id: Annotated[int | None, Field(description="New parent category ID")] = None,
        clear_category: bool = False,
        sync_permissions: bool | None = None,
        reason: Annotated[str, Field(max_length=512)] = "MCP admin action",
    ) -> dict:
        return await service.move_channel(guild_id, channel_id, position, category_id, clear_category, sync_permissions, reason)

    @server.tool(title="List Discord webhooks", annotations=read_only)
    async def discord_list_webhooks(guild_id: Annotated[int, Field(description="Discord guild/server ID")]) -> dict:
        return await service.list_webhooks(guild_id)

    @server.tool(title="Create Discord webhook", annotations=write)
    async def discord_create_webhook(
        guild_id: Annotated[int, Field(description="Discord guild/server ID")],
        channel_id: Annotated[int, Field(description="Discord channel ID")],
        name: Annotated[str, Field(min_length=1, max_length=80)],
        reason: Annotated[str, Field(max_length=512)] = "MCP admin action",
    ) -> dict:
        return await service.create_webhook(guild_id, channel_id, name, reason)

    @server.tool(title="Update Discord webhook", annotations=write)
    async def discord_update_webhook(
        guild_id: Annotated[int, Field(description="Discord guild/server ID")],
        webhook_id: Annotated[int, Field(description="Discord webhook ID")],
        name: Annotated[str | None, Field(min_length=1, max_length=80)] = None,
        channel_id: Annotated[int | None, Field(description="Move webhook to this channel")]=None,
        reason: Annotated[str, Field(max_length=512)] = "MCP admin action",
    ) -> dict:
        return await service.update_webhook(guild_id, webhook_id, name, channel_id, reason)

    @server.tool(title="Delete Discord webhook", annotations=destructive)
    async def discord_delete_webhook(
        guild_id: Annotated[int, Field(description="Discord guild/server ID")],
        webhook_id: Annotated[int, Field(description="Discord webhook ID")],
        reason: Annotated[str, Field(max_length=512)] = "MCP admin action",
    ) -> dict:
        return await service.delete_webhook(guild_id, webhook_id, reason)

    @server.tool(title="List Discord emojis", annotations=read_only)
    async def discord_list_emojis(guild_id: Annotated[int, Field(description="Discord guild/server ID")]) -> dict:
        return await service.list_emojis(guild_id)

    @server.tool(title="Create Discord emoji", annotations=write)
    async def discord_create_emoji(
        guild_id: Annotated[int, Field(description="Discord guild/server ID")],
        name: Annotated[str, Field(min_length=2, max_length=32)],
        image_base64: Annotated[str, Field(min_length=1, max_length=400_000, description="Base64 image data or data URI")],
        reason: Annotated[str, Field(max_length=512)] = "MCP admin action",
    ) -> dict:
        return await service.create_emoji(guild_id, name, image_base64, reason)

    @server.tool(title="Update Discord emoji", annotations=write)
    async def discord_update_emoji(
        guild_id: Annotated[int, Field(description="Discord guild/server ID")],
        emoji_id: Annotated[int, Field(description="Discord emoji ID")],
        name: Annotated[str | None, Field(min_length=2, max_length=32)] = None,
        role_ids: Annotated[list[int] | None, Field(description="Roles allowed to use this emoji; empty list means unrestricted")] = None,
        reason: Annotated[str, Field(max_length=512)] = "MCP admin action",
    ) -> dict:
        return await service.update_emoji(guild_id, emoji_id, name, role_ids, reason)

    @server.tool(title="Delete Discord emoji", annotations=destructive)
    async def discord_delete_emoji(
        guild_id: Annotated[int, Field(description="Discord guild/server ID")],
        emoji_id: Annotated[int, Field(description="Discord emoji ID")],
        reason: Annotated[str, Field(max_length=512)] = "MCP admin action",
    ) -> dict:
        return await service.delete_emoji(guild_id, emoji_id, reason)

    @server.tool(title="List Discord stickers", annotations=read_only)
    async def discord_list_stickers(guild_id: Annotated[int, Field(description="Discord guild/server ID")]) -> dict:
        return await service.list_stickers(guild_id)

    @server.tool(title="Create Discord sticker", annotations=write)
    async def discord_create_sticker(
        guild_id: Annotated[int, Field(description="Discord guild/server ID")],
        name: Annotated[str, Field(min_length=2, max_length=30)],
        description: Annotated[str, Field(min_length=2, max_length=100)],
        emoji: Annotated[str, Field(min_length=1, max_length=64, description="Unicode emoji tag")],
        image_base64: Annotated[str, Field(min_length=1, max_length=800_000, description="Base64 PNG/APNG/Lottie data or data URI")],
        filename: Annotated[str, Field(min_length=1, max_length=128)] = "sticker.png",
        reason: Annotated[str, Field(max_length=512)] = "MCP admin action",
    ) -> dict:
        return await service.create_sticker(guild_id, name, description, emoji, image_base64, filename, reason)

    @server.tool(title="Update Discord sticker", annotations=write)
    async def discord_update_sticker(
        guild_id: Annotated[int, Field(description="Discord guild/server ID")],
        sticker_id: Annotated[int, Field(description="Discord sticker ID")],
        name: Annotated[str | None, Field(min_length=2, max_length=30)] = None,
        description: Annotated[str | None, Field(min_length=2, max_length=100)] = None,
        emoji: Annotated[str | None, Field(min_length=1, max_length=64)] = None,
        reason: Annotated[str, Field(max_length=512)] = "MCP admin action",
    ) -> dict:
        return await service.update_sticker(guild_id, sticker_id, name, description, emoji, reason)

    @server.tool(title="Delete Discord sticker", annotations=destructive)
    async def discord_delete_sticker(
        guild_id: Annotated[int, Field(description="Discord guild/server ID")],
        sticker_id: Annotated[int, Field(description="Discord sticker ID")],
        reason: Annotated[str, Field(max_length=512)] = "MCP admin action",
    ) -> dict:
        return await service.delete_sticker(guild_id, sticker_id, reason)

    @server.tool(title="Set Discord member nickname", annotations=write)
    async def discord_set_member_nickname(
        guild_id: Annotated[int, Field(description="Discord guild/server ID")],
        user_id: Annotated[int, Field(description="Discord user ID")],
        nickname: Annotated[str | None, Field(max_length=32, description="New nickname; null/empty clears it")],
        reason: Annotated[str, Field(max_length=512)] = "MCP admin action",
    ) -> dict:
        return await service.set_member_nickname(guild_id, user_id, nickname, reason)

    @server.tool(title="Move/disconnect Discord voice member", annotations=write)
    async def discord_move_member_voice(
        guild_id: Annotated[int, Field(description="Discord guild/server ID")],
        user_id: Annotated[int, Field(description="Discord user ID")],
        channel_id: Annotated[int | None, Field(description="Voice/stage channel ID; null disconnects")],
        reason: Annotated[str, Field(max_length=512)] = "MCP admin action",
    ) -> dict:
        return await service.move_member_voice(guild_id, user_id, channel_id, reason)

    @server.tool(title="Set Discord server mute/deafen", annotations=write)
    async def discord_set_member_voice_state(
        guild_id: Annotated[int, Field(description="Discord guild/server ID")],
        user_id: Annotated[int, Field(description="Discord user ID")],
        mute: bool | None = None,
        deafen: bool | None = None,
        reason: Annotated[str, Field(max_length=512)] = "MCP admin action",
    ) -> dict:
        return await service.set_member_voice_state(guild_id, user_id, mute, deafen, reason)

    @server.tool(title="List Discord invites", annotations=read_only)
    async def discord_list_invites(guild_id: Annotated[int, Field(description="Discord guild/server ID")]) -> dict:
        return await service.list_invites(guild_id)

    @server.tool(title="Create Discord invite", annotations=write)
    async def discord_create_invite(
        guild_id: Annotated[int, Field(description="Discord guild/server ID")],
        channel_id: Annotated[int, Field(description="Discord channel ID")],
        max_age: Annotated[int, Field(ge=0, le=604_800)] = 0,
        max_uses: Annotated[int, Field(ge=0, le=100)] = 0,
        temporary: bool = False,
        unique: bool = True,
        reason: Annotated[str, Field(max_length=512)] = "MCP admin action",
    ) -> dict:
        return await service.create_invite(guild_id, channel_id, max_age, max_uses, temporary, unique, reason)

    @server.tool(title="Delete Discord invite", annotations=destructive)
    async def discord_delete_invite(
        guild_id: Annotated[int, Field(description="Discord guild/server ID")],
        code: Annotated[str, Field(min_length=1, max_length=64, description="Discord invite code")],
        reason: Annotated[str, Field(max_length=512)] = "MCP admin action",
    ) -> dict:
        return await service.delete_invite(guild_id, code, reason)

    @server.tool(title="List active Discord threads", annotations=read_only)
    async def discord_list_threads(guild_id: Annotated[int, Field(description="Discord guild/server ID")]) -> dict:
        return await service.list_threads(guild_id)

    @server.tool(title="Create Discord thread", annotations=write)
    async def discord_create_thread(
        guild_id: Annotated[int, Field(description="Discord guild/server ID")],
        channel_id: Annotated[int, Field(description="Parent channel ID")],
        name: Annotated[str, Field(min_length=1, max_length=100)],
        auto_archive_duration: Annotated[int, Field(description="60, 1440, 4320, or 10080 minutes")] = 1440,
        slowmode_delay: Annotated[int, Field(ge=0, le=21_600)] = 0,
        reason: Annotated[str, Field(max_length=512)] = "MCP admin action",
    ) -> dict:
        return await service.create_thread(guild_id, channel_id, name, auto_archive_duration, slowmode_delay, reason)

    @server.tool(title="Update Discord thread", annotations=write)
    async def discord_update_thread(
        guild_id: Annotated[int, Field(description="Discord guild/server ID")],
        thread_id: Annotated[int, Field(description="Discord thread ID")],
        name: Annotated[str | None, Field(min_length=1, max_length=100)] = None,
        archived: bool | None = None,
        locked: bool | None = None,
        auto_archive_duration: Annotated[int | None, Field(description="60, 1440, 4320, or 10080 minutes")] = None,
        slowmode_delay: Annotated[int | None, Field(ge=0, le=21_600)] = None,
        reason: Annotated[str, Field(max_length=512)] = "MCP admin action",
    ) -> dict:
        return await service.update_thread(guild_id, thread_id, name, archived, locked, auto_archive_duration, slowmode_delay, reason)

    @server.tool(title="Delete Discord thread", annotations=destructive)
    async def discord_delete_thread(
        guild_id: Annotated[int, Field(description="Discord guild/server ID")],
        thread_id: Annotated[int, Field(description="Discord thread ID")],
        reason: Annotated[str, Field(max_length=512)] = "MCP admin action",
    ) -> dict:
        return await service.delete_thread(guild_id, thread_id, reason)

    @server.tool(title="Pin Discord message", annotations=write)
    async def discord_pin_message(
        guild_id: Annotated[int, Field(description="Discord guild/server ID")],
        channel_id: Annotated[int, Field(description="Discord channel/thread ID")],
        message_id: Annotated[int, Field(description="Discord message ID")],
        reason: Annotated[str, Field(max_length=512)] = "MCP admin action",
    ) -> dict:
        return await service.pin_message(guild_id, channel_id, message_id, reason)

    @server.tool(title="Unpin Discord message", annotations=destructive)
    async def discord_unpin_message(
        guild_id: Annotated[int, Field(description="Discord guild/server ID")],
        channel_id: Annotated[int, Field(description="Discord channel/thread ID")],
        message_id: Annotated[int, Field(description="Discord message ID")],
        reason: Annotated[str, Field(max_length=512)] = "MCP admin action",
    ) -> dict:
        return await service.unpin_message(guild_id, channel_id, message_id, reason)

    @server.tool(title="Purge Discord messages", annotations=destructive)
    async def discord_purge_messages(
        guild_id: Annotated[int, Field(description="Discord guild/server ID")],
        channel_id: Annotated[int, Field(description="Discord text channel ID")],
        limit: Annotated[int, Field(ge=1, le=100, description="Maximum recent messages to scan")],
        user_id: Annotated[int | None, Field(description="Optional author filter")] = None,
        contains: Annotated[str | None, Field(max_length=2000, description="Optional substring filter")] = None,
        reason: Annotated[str, Field(max_length=512)] = "MCP admin action",
    ) -> dict:
        return await service.purge_messages(guild_id, channel_id, limit, user_id, contains, reason)

    registered = {name for name in locals() if name.startswith("discord_")}
    assert registered == EXTENDED_TOOL_NAMES
    return registered
