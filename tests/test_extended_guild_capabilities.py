import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from services.extended_discord_admin_service import ExtendedDiscordAdminService


@pytest.mark.asyncio
async def test_list_guilds_reports_permissions_used_by_extended_tools():
    service = ExtendedDiscordAdminService()
    bot = MagicMock()
    bot.is_closed.return_value = False
    bot.is_ready.return_value = True

    permissions = SimpleNamespace(
        manage_messages=True,
        moderate_members=True,
        kick_members=True,
        ban_members=True,
        manage_roles=True,
        manage_channels=True,
        manage_guild=True,
        manage_webhooks=True,
        manage_emojis_and_stickers=True,
        manage_nicknames=True,
        move_members=True,
        mute_members=True,
        deafen_members=True,
        manage_threads=True,
        create_public_threads=True,
        create_private_threads=True,
        create_instant_invite=True,
        view_audit_log=True,
    )
    guild = SimpleNamespace(
        id=123,
        name="Admin Test",
        member_count=10,
        owner_id=1,
        text_channels=[object()],
        voice_channels=[object()],
        me=SimpleNamespace(guild_permissions=permissions),
    )
    bot.guilds = [guild]
    service.bot_service = SimpleNamespace(bot=bot, bot_loop=None)

    with patch.dict(os.environ, {"DISCORD_ADMIN_GUILD_IDS": "123"}, clear=True):
        result = await service.list_guilds()

    assert result["success"] is True
    capabilities = result["guilds"][0]["capabilities"]
    assert capabilities == {
        "manage_messages": True,
        "moderate_members": True,
        "kick_members": True,
        "ban_members": True,
        "manage_roles": True,
        "manage_channels": True,
        "manage_guild": True,
        "manage_webhooks": True,
        "manage_emojis_and_stickers": True,
        "manage_nicknames": True,
        "move_members": True,
        "mute_members": True,
        "deafen_members": True,
        "manage_threads": True,
        "create_public_threads": True,
        "create_private_threads": True,
        "create_instant_invite": True,
        "view_audit_log": True,
    }
