import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_server import _transport_security
from services.discord_admin_service import DiscordAdminService


def _service_with_bot(guilds=None):
    service = DiscordAdminService()
    bot = MagicMock()
    bot.is_closed.return_value = False
    bot.is_ready.return_value = True
    bot.guilds = guilds or []
    service.bot_service = SimpleNamespace(bot=bot, bot_loop=None)
    return service, bot


def test_policy_requires_explicit_allowlist():
    service, _ = _service_with_bot()

    with patch.dict(os.environ, {}, clear=True):
        assert service.is_guild_allowed(123) is False

    with patch.dict(os.environ, {"DISCORD_ADMIN_GUILD_IDS": "123,456"}, clear=True):
        assert service.is_guild_allowed(123) is True
        assert service.is_guild_allowed(999) is False

    with patch.dict(os.environ, {"DISCORD_ADMIN_GUILD_IDS": "*"}, clear=True):
        assert service.is_guild_allowed(999) is True


def test_transport_security_derives_host_from_domain_name():
    with patch.dict(os.environ, {"DOMAIN_NAME": "nstut.cloud"}, clear=True):
        settings = _transport_security()

    assert "localhost:*" in settings.allowed_hosts
    assert "lily-discord-adapter.nstut.cloud" in settings.allowed_hosts
    assert "lily-discord-adapter.nstut.cloud:*" in settings.allowed_hosts
    assert settings.allowed_origins == []


def test_transport_security_explicit_hosts_override_domain_default():
    with patch.dict(
        os.environ,
        {
            "DOMAIN_NAME": "nstut.cloud",
            "MCP_ALLOWED_HOSTS": "mcp.example.com,mcp.example.com:*",
            "MCP_ALLOWED_ORIGINS": "https://example.com",
        },
        clear=True,
    ):
        settings = _transport_security()

    assert settings.allowed_hosts == ["mcp.example.com", "mcp.example.com:*"]
    assert settings.allowed_origins == ["https://example.com"]


@pytest.mark.asyncio
async def test_send_message_is_guild_scoped_and_disables_mentions():
    service, bot = _service_with_bot()
    guild = MagicMock()
    guild.id = 123
    guild.name = "Test"
    channel = MagicMock()
    channel.id = 456

    sent = SimpleNamespace(id=789)
    channel.send = AsyncMock(return_value=sent)
    guild.get_channel.return_value = channel
    bot.get_guild.return_value = guild

    with (
        patch.dict(os.environ, {"DISCORD_ADMIN_GUILD_IDS": "123"}, clear=True),
        patch("services.discord_admin_service.discord.TextChannel", new=type(channel)),
    ):
        result = await service.send_message(123, 456, "hello")

    assert result["success"] is True
    channel.send.assert_awaited_once()
    kwargs = channel.send.await_args.kwargs
    assert kwargs["allowed_mentions"].everyone is False
    assert kwargs["allowed_mentions"].roles is False
    assert kwargs["allowed_mentions"].users is False


@pytest.mark.asyncio
async def test_disallowed_guild_cannot_be_mutated():
    service, bot = _service_with_bot()
    bot.get_guild.return_value = MagicMock()

    with patch.dict(os.environ, {"DISCORD_ADMIN_GUILD_IDS": "123"}, clear=True):
        result = await service.timeout_member(999, 111, 60, "test")

    assert result["success"] is False
    assert "not enabled" in result["message"]
