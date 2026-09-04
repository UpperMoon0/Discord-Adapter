import base64
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from mcp_extended_tools import EXTENDED_TOOL_NAMES, register_extended_tools
from services.extended_discord_admin_service import ExtendedDiscordAdminService


GUILD_ID = 123


def _service_with_bot():
    service = ExtendedDiscordAdminService()
    bot = MagicMock()
    bot.is_closed.return_value = False
    bot.is_ready.return_value = True
    service.bot_service = SimpleNamespace(bot=bot, bot_loop=None)
    return service, bot


def _allowed():
    return patch.dict(os.environ, {"DISCORD_ADMIN_GUILD_IDS": str(GUILD_ID)}, clear=True)


def _guild(bot):
    guild = MagicMock()
    guild.id = GUILD_ID
    guild.name = "Test Guild"
    guild.get_thread.return_value = None
    bot.get_guild.return_value = guild
    return guild


class FakeMCPServer:
    def __init__(self):
        self.tools = {}

    def tool(self, **metadata):
        def decorator(function):
            self.tools[function.__name__] = metadata
            return function

        return decorator


def test_extended_tool_registration_is_complete_and_semantic():
    server = FakeMCPServer()
    read_only = object()
    write = object()
    destructive = object()

    registered = register_extended_tools(server, object(), read_only, write, destructive)

    assert registered == EXTENDED_TOOL_NAMES
    assert set(server.tools) == EXTENDED_TOOL_NAMES
    assert server.tools["discord_list_webhooks"]["annotations"] is read_only
    assert server.tools["discord_create_role"]["annotations"] is write
    assert server.tools["discord_purge_messages"]["annotations"] is destructive


@pytest.mark.asyncio
async def test_extended_operations_remain_guild_scoped():
    service, bot = _service_with_bot()
    bot.get_guild.return_value = MagicMock()

    with patch.dict(os.environ, {"DISCORD_ADMIN_GUILD_IDS": str(GUILD_ID)}, clear=True):
        result = await service.create_role(999, "Nope")

    assert result["success"] is False
    assert "not enabled" in result["message"]


@pytest.mark.asyncio
async def test_role_crud_and_permission_translation():
    service, bot = _service_with_bot()
    guild = _guild(bot)
    role = MagicMock()
    role.id = 10
    role.name = "Moderator"
    role.position = 3
    role.managed = False
    role.is_default.return_value = False
    role.edit = AsyncMock(return_value=role)
    role.delete = AsyncMock()
    guild.create_role = AsyncMock(return_value=role)
    guild.get_role.return_value = role

    with _allowed():
        created = await service.create_role(
            GUILD_ID,
            "Moderator",
            permissions=["manage_messages", "kick_members"],
            colour=0x112233,
            hoist=True,
            mentionable=True,
            reason="test",
        )
        updated = await service.update_role(
            GUILD_ID,
            role.id,
            name="Senior Moderator",
            permissions=["manage_messages"],
            position=4,
            reason="test",
        )
        deleted = await service.delete_role(GUILD_ID, role.id, "test")

    assert created["success"] is True
    create_kwargs = guild.create_role.await_args.kwargs
    assert create_kwargs["permissions"].manage_messages is True
    assert create_kwargs["permissions"].kick_members is True
    assert create_kwargs["colour"].value == 0x112233
    assert updated["success"] is True
    assert role.edit.await_args.kwargs["position"] == 4
    assert deleted["success"] is True
    role.delete.assert_awaited_once_with(reason="test")


@pytest.mark.asyncio
async def test_role_crud_rejects_unknown_permissions_and_managed_roles():
    service, bot = _service_with_bot()
    guild = _guild(bot)
    role = MagicMock()
    role.id = 10
    role.managed = True
    role.is_default.return_value = False
    guild.get_role.return_value = role

    unknown = await service.create_role(GUILD_ID, "bad", permissions=["not_a_permission"])
    with _allowed():
        managed = await service.delete_role(GUILD_ID, role.id)

    assert unknown["success"] is False
    assert "unknown Discord permissions" in unknown["message"]
    assert managed["success"] is False
    assert "managed" in managed["message"]


@pytest.mark.asyncio
async def test_get_and_update_guild_settings_with_enum_aliases():
    service, bot = _service_with_bot()
    guild = _guild(bot)
    guild.verification_level = discord.VerificationLevel.low
    guild.default_notifications = discord.NotificationLevel.only_mentions
    guild.explicit_content_filter = discord.ContentFilter.disabled
    guild.afk_channel = None
    guild.afk_timeout = 300
    guild.system_channel = None
    guild.description = None
    edited = MagicMock(name="edited_guild")
    edited.name = "Renamed"
    guild.edit = AsyncMock(return_value=edited)

    with _allowed():
        current = await service.get_guild_settings(GUILD_ID)
        result = await service.update_guild_settings(
            GUILD_ID,
            name="Renamed",
            verification_level="high",
            default_notifications="mentions",
            explicit_content_filter="all",
            afk_timeout=900,
            reason="settings",
        )

    assert current["success"] is True
    assert current["settings"]["verification_level"] == "low"
    assert result["success"] is True
    kwargs = guild.edit.await_args.kwargs
    assert kwargs["verification_level"] is discord.VerificationLevel.high
    assert kwargs["default_notifications"] is discord.NotificationLevel.only_mentions
    assert kwargs["explicit_content_filter"] is discord.ContentFilter.all_members
    assert kwargs["afk_timeout"] == 900


@pytest.mark.asyncio
async def test_channel_permission_overwrite_set_and_clear():
    service, bot = _service_with_bot()
    guild = _guild(bot)
    channel = MagicMock()
    channel.id = 20
    channel.set_permissions = AsyncMock()
    role = MagicMock()
    role.id = 30
    guild.get_channel.return_value = channel
    guild.get_role.return_value = role

    with _allowed():
        set_result = await service.set_channel_permissions(
            GUILD_ID,
            channel.id,
            "role",
            role.id,
            {"send_messages": False, "view_channel": True},
            "permissions",
        )
        clear_result = await service.clear_channel_permissions(
            GUILD_ID, channel.id, "role", role.id, "permissions"
        )

    assert set_result["success"] is True
    first = channel.set_permissions.await_args_list[0]
    overwrite = first.kwargs["overwrite"]
    assert overwrite.send_messages is False
    assert overwrite.view_channel is True
    assert clear_result["success"] is True
    assert channel.set_permissions.await_args_list[1].kwargs["overwrite"] is None


@pytest.mark.asyncio
async def test_channel_permission_overwrite_rejects_unknown_flag():
    service, _ = _service_with_bot()
    result = await service.set_channel_permissions(
        GUILD_ID, 1, "role", 2, {"super_admin": True}
    )
    assert result["success"] is False
    assert "unknown Discord permissions" in result["message"]


@pytest.mark.asyncio
async def test_update_channel_renames_any_guild_channel():
    service, bot = _service_with_bot()
    guild = _guild(bot)
    channel = MagicMock()
    channel.id = 54
    channel.name = "Old Name"
    channel.type = discord.ChannelType.voice
    channel.edit = AsyncMock()
    edited = MagicMock()
    edited.id = channel.id
    edited.name = "Voice Lounge"
    edited.type = discord.ChannelType.voice
    channel.edit.return_value = edited
    guild.get_channel.return_value = channel

    with _allowed():
        result = await service.update_channel(GUILD_ID, channel.id, " Voice Lounge ", "rename")

    assert result == {
        "success": True,
        "guild_id": GUILD_ID,
        "channel_id": channel.id,
        "channel_name": "Voice Lounge",
        "channel_type": str(discord.ChannelType.voice),
    }
    channel.edit.assert_awaited_once_with(name="Voice Lounge", reason="rename")


@pytest.mark.asyncio
async def test_update_channel_validates_name_and_missing_channel():
    service, bot = _service_with_bot()
    guild = _guild(bot)
    guild.get_channel.return_value = None

    invalid = await service.update_channel(GUILD_ID, 54, "   ")
    with _allowed():
        missing = await service.update_channel(GUILD_ID, 54, "renamed")

    assert invalid["success"] is False
    assert "1-100" in invalid["message"]
    assert missing["success"] is False
    assert "not found" in missing["message"]


@pytest.mark.asyncio
async def test_move_channel_supports_category_and_position():
    service, bot = _service_with_bot()
    guild = _guild(bot)

    class Category:
        id = 77

    class Channel:
        id = 55
        position = 2
        category_id = 77

        def __init__(self):
            self.edit = AsyncMock(return_value=self)

    category = Category()
    channel = Channel()
    guild.get_channel.side_effect = lambda cid: channel if cid == 55 else category if cid == 77 else None

    with _allowed(), patch("services.discord_admin_extensions.discord.CategoryChannel", new=Category):
        result = await service.move_channel(
            GUILD_ID, 55, position=2, category_id=77, sync_permissions=True, reason="move"
        )

    assert result["success"] is True
    kwargs = channel.edit.await_args.kwargs
    assert kwargs["category"] is category
    assert kwargs["position"] == 2
    assert kwargs["sync_permissions"] is True


@pytest.mark.asyncio
async def test_webhook_crud_never_requires_exposing_webhook_tokens():
    service, bot = _service_with_bot()
    guild = _guild(bot)
    channel = MagicMock()
    channel.id = 5
    channel.create_webhook = AsyncMock()
    hook = MagicMock()
    hook.id = 6
    hook.name = "ops"
    hook.channel_id = 5
    hook.type = "incoming"
    hook.user = None
    hook.application_id = None
    hook.edit = AsyncMock(return_value=hook)
    hook.delete = AsyncMock()
    channel.create_webhook.return_value = hook
    guild.get_channel.return_value = channel
    guild.webhooks = AsyncMock(return_value=[hook])

    with _allowed():
        listed = await service.list_webhooks(GUILD_ID)
        created = await service.create_webhook(GUILD_ID, channel.id, "ops", "webhook")
        updated = await service.update_webhook(GUILD_ID, hook.id, name="ops-2", reason="webhook")
        deleted = await service.delete_webhook(GUILD_ID, hook.id, "webhook")

    assert listed["success"] is True
    assert "url" not in listed["webhooks"][0]
    assert created["success"] is True
    assert updated["success"] is True
    assert deleted["success"] is True


@pytest.mark.asyncio
async def test_emoji_crud_and_base64_validation():
    service, bot = _service_with_bot()
    guild = _guild(bot)
    emoji = MagicMock()
    emoji.id = 7
    emoji.name = "lily"
    emoji.animated = False
    emoji.available = True
    emoji.managed = False
    emoji.roles = []
    emoji.edit = AsyncMock(return_value=emoji)
    emoji.delete = AsyncMock()
    guild.emojis = [emoji]
    guild.get_emoji.return_value = emoji
    guild.create_custom_emoji = AsyncMock(return_value=emoji)
    payload = base64.b64encode(b"small-image").decode()

    invalid = await service.create_emoji(GUILD_ID, "lily", "%%%")
    with _allowed():
        listed = await service.list_emojis(GUILD_ID)
        created = await service.create_emoji(GUILD_ID, "lily", payload, "emoji")
        updated = await service.update_emoji(GUILD_ID, emoji.id, name="lily2", reason="emoji")
        deleted = await service.delete_emoji(GUILD_ID, emoji.id, "emoji")

    assert invalid["success"] is False
    assert "base64" in invalid["message"]
    assert listed["success"] is True
    assert created["success"] is True
    assert guild.create_custom_emoji.await_args.kwargs["image"] == b"small-image"
    assert updated["success"] is True
    assert deleted["success"] is True


@pytest.mark.asyncio
async def test_sticker_crud_uses_bounded_in_memory_upload():
    service, bot = _service_with_bot()
    guild = _guild(bot)
    sticker = MagicMock()
    sticker.id = 8
    sticker.name = "wave"
    sticker.description = "hello"
    sticker.emoji = "👋"
    sticker.available = True
    sticker.format = "png"
    sticker.edit = AsyncMock(return_value=sticker)
    sticker.delete = AsyncMock()
    guild.stickers = [sticker]
    guild.get_sticker.return_value = sticker
    guild.create_sticker = AsyncMock(return_value=sticker)
    payload = base64.b64encode(b"sticker-data").decode()

    with _allowed(), patch("services.discord_admin_extensions.discord.File") as file_type:
        listed = await service.list_stickers(GUILD_ID)
        created = await service.create_sticker(
            GUILD_ID, "wave", "hello", "👋", payload, "wave.png", "sticker"
        )
        updated = await service.update_sticker(GUILD_ID, sticker.id, name="wave2", reason="sticker")
        deleted = await service.delete_sticker(GUILD_ID, sticker.id, "sticker")

    assert listed["success"] is True
    assert created["success"] is True
    file_type.assert_called_once()
    assert updated["success"] is True
    assert deleted["success"] is True


@pytest.mark.asyncio
async def test_nickname_and_voice_administration():
    service, bot = _service_with_bot()
    guild = _guild(bot)
    member = MagicMock()
    member.id = 9
    member.edit = AsyncMock(return_value=SimpleNamespace(nick="Builder"))
    member.move_to = AsyncMock()
    guild.get_member.return_value = member

    with _allowed():
        nick = await service.set_member_nickname(GUILD_ID, member.id, "Builder", "nick")
        disconnected = await service.move_member_voice(GUILD_ID, member.id, None, "voice")
        voice_state = await service.set_member_voice_state(
            GUILD_ID, member.id, mute=True, deafen=False, reason="voice"
        )

    assert nick["success"] is True
    member.move_to.assert_awaited_once_with(None, reason="voice")
    assert disconnected["success"] is True
    assert voice_state["success"] is True
    assert member.edit.await_args_list[-1].kwargs["mute"] is True
    assert member.edit.await_args_list[-1].kwargs["deafen"] is False


@pytest.mark.asyncio
async def test_invite_crud_is_scoped_to_guild_invites():
    service, bot = _service_with_bot()
    guild = _guild(bot)
    channel = MagicMock()
    channel.id = 10
    invite = MagicMock()
    invite.code = "abc123"
    invite.channel = channel
    invite.inviter = None
    invite.max_age = 3600
    invite.max_uses = 5
    invite.uses = 1
    invite.temporary = False
    invite.expires_at = None
    invite.delete = AsyncMock()
    channel.create_invite = AsyncMock(return_value=invite)
    guild.get_channel.return_value = channel
    guild.invites = AsyncMock(return_value=[invite])

    with _allowed():
        listed = await service.list_invites(GUILD_ID)
        created = await service.create_invite(GUILD_ID, channel.id, 3600, 5, False, True, "invite")
        deleted = await service.delete_invite(GUILD_ID, invite.code, "invite")

    assert listed["success"] is True
    assert created["code"] == "abc123"
    assert deleted["success"] is True
    invite.delete.assert_awaited_once_with(reason="invite")


@pytest.mark.asyncio
async def test_thread_crud():
    service, bot = _service_with_bot()
    guild = _guild(bot)
    channel = MagicMock()
    channel.id = 11
    thread = MagicMock()
    thread.id = 12
    thread.name = "ops"
    thread.parent_id = channel.id
    thread.owner_id = 99
    thread.archived = False
    thread.locked = False
    thread.auto_archive_duration = 1440
    thread.slowmode_delay = 0
    thread.message_count = 2
    thread.edit = AsyncMock(return_value=thread)
    thread.delete = AsyncMock()
    channel.create_thread = AsyncMock(return_value=thread)
    guild.get_channel.return_value = channel
    guild.get_thread.return_value = thread
    guild.threads = [thread]

    with _allowed():
        listed = await service.list_threads(GUILD_ID)
        created = await service.create_thread(GUILD_ID, channel.id, "ops", 1440, 0, "thread")
        updated = await service.update_thread(GUILD_ID, thread.id, archived=True, locked=True, reason="thread")
        deleted = await service.delete_thread(GUILD_ID, thread.id, "thread")

    assert listed["threads"][0]["id"] == thread.id
    assert created["success"] is True
    assert updated["success"] is True
    assert thread.edit.await_args.kwargs["archived"] is True
    assert thread.edit.await_args.kwargs["locked"] is True
    assert deleted["success"] is True


@pytest.mark.asyncio
async def test_pin_unpin_and_filtered_purge():
    service, bot = _service_with_bot()
    guild = _guild(bot)
    channel = MagicMock()
    channel.id = 13
    message = MagicMock()
    message.id = 14
    message.pin = AsyncMock()
    message.unpin = AsyncMock()
    channel.fetch_message = AsyncMock(return_value=message)
    deleted = [SimpleNamespace(id=15), SimpleNamespace(id=16)]
    channel.purge = AsyncMock(return_value=deleted)
    guild.get_channel.return_value = channel

    with _allowed():
        pinned = await service.pin_message(GUILD_ID, channel.id, message.id, "pin")
        unpinned = await service.unpin_message(GUILD_ID, channel.id, message.id, "pin")
        purged = await service.purge_messages(
            GUILD_ID, channel.id, 25, user_id=99, contains="spam", reason="purge"
        )

    assert pinned["pinned"] is True
    assert unpinned["pinned"] is False
    assert purged["deleted_count"] == 2
    kwargs = channel.purge.await_args.kwargs
    assert kwargs["limit"] == 25
    assert callable(kwargs["check"])
    matching = SimpleNamespace(author=SimpleNamespace(id=99), content="contains spam here")
    wrong_user = SimpleNamespace(author=SimpleNamespace(id=100), content="contains spam here")
    assert kwargs["check"](matching) is True
    assert kwargs["check"](wrong_user) is False


@pytest.mark.asyncio
async def test_configure_channel_consolidates_text_and_move_updates():
    service, bot = _service_with_bot()
    guild = _guild(bot)

    class Category:
        id = 77

    class TextChannel:
        id = 55
        name = "general"
        type = discord.ChannelType.text
        position = 1
        category_id = None

        def __init__(self):
            self.edit = AsyncMock(return_value=self)

    category = Category()
    channel = TextChannel()
    guild.get_channel.side_effect = lambda cid: channel if cid == 55 else category if cid == 77 else None

    with (
        _allowed(),
        patch("services.extended_discord_admin_service.discord.TextChannel", new=TextChannel),
        patch("services.extended_discord_admin_service.discord.CategoryChannel", new=Category),
    ):
        result = await service.configure_channel(
            GUILD_ID,
            55,
            name="ops",
            topic="operations",
            slowmode_delay=5,
            position=3,
            category_id=77,
            sync_permissions=True,
            reason="compact update",
        )

    assert result["success"] is True
    kwargs = channel.edit.await_args.kwargs
    assert kwargs["name"] == "ops"
    assert kwargs["topic"] == "operations"
    assert kwargs["slowmode_delay"] == 5
    assert kwargs["position"] == 3
    assert kwargs["category"] is category
    assert kwargs["sync_permissions"] is True
    assert kwargs["reason"] == "compact update"
