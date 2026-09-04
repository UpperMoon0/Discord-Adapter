import os
from types import MappingProxyType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_server import _transport_security
from services.access_policy_service import PolicySnapshot, access_policy_service
from services.discord_admin_service import DiscordAdminService


def _service_with_bot(guilds=None):
    service = DiscordAdminService()
    bot = MagicMock()
    bot.is_closed.return_value = False
    bot.is_ready.return_value = True
    bot.guilds = guilds or []
    bot.intents = SimpleNamespace(members=True)
    service.bot_service = SimpleNamespace(bot=bot, bot_loop=None)
    return service, bot


def _runtime_policy(*guild_ids, all_guilds=False):
    snapshot = PolicySnapshot(
        version=1,
        revision=1,
        all_guilds=all_guilds,
        guilds=MappingProxyType({guild_id: frozenset() for guild_id in guild_ids}),
        source="test",
    )
    return patch.object(access_policy_service, "_snapshot", snapshot)


def test_policy_requires_explicit_runtime_allowlist():
    service, _ = _service_with_bot()

    with _runtime_policy():
        assert service.is_guild_allowed(123) is False

    with _runtime_policy(123, 456):
        assert service.is_guild_allowed(123) is True
        assert service.is_guild_allowed(999) is False

    with _runtime_policy(all_guilds=True):
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
        _runtime_policy(123),
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
async def test_send_message_can_ping_only_explicit_users_and_roles():
    service, bot = _service_with_bot()
    guild = MagicMock(); guild.id = 123; guild.name = "Test"
    guild.get_member.side_effect = lambda user_id: SimpleNamespace(id=user_id) if user_id == 111 else None
    guild.get_role.side_effect = lambda role_id: SimpleNamespace(id=role_id) if role_id == 222 else None
    channel = MagicMock(); channel.id = 456
    channel.send = AsyncMock(return_value=SimpleNamespace(id=789))
    guild.get_channel.return_value = channel; bot.get_guild.return_value = guild
    with (_runtime_policy(123), patch("services.discord_admin_service.discord.TextChannel", new=type(channel))):
        result = await service.send_message(123, 456, "hello @everyone", mention_user_ids=[111], mention_role_ids=[222])
    assert result["success"] is True
    assert result["content"].startswith("<@111> <@&222> ")
    allowed = channel.send.await_args.kwargs["allowed_mentions"]
    assert allowed.everyone is False
    assert [item.id for item in allowed.users] == [111]
    assert [item.id for item in allowed.roles] == [222]
    assert allowed.replied_user is False


@pytest.mark.asyncio
async def test_send_message_rejects_unknown_explicit_mention_target():
    service, bot = _service_with_bot()
    guild = MagicMock(); guild.id = 123; guild.get_member.return_value = None
    guild.fetch_member = AsyncMock(return_value=None)
    channel = MagicMock(); channel.id = 456; channel.send = AsyncMock()
    guild.get_channel.return_value = channel; bot.get_guild.return_value = guild
    with (_runtime_policy(123), patch("services.discord_admin_service.discord.TextChannel", new=type(channel))):
        result = await service.send_message(123, 456, "hello", mention_user_ids=[999])
    assert result["success"] is False
    assert "not members" in result["message"]
    channel.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_message_can_reply_without_pinging_reply_author():
    service, bot = _service_with_bot()
    guild = MagicMock(); guild.id = 123
    channel = MagicMock(); channel.id = 456
    original = SimpleNamespace(id=654)
    channel.fetch_message = AsyncMock(return_value=original)
    channel.send = AsyncMock(return_value=SimpleNamespace(id=789))
    guild.get_channel.return_value = channel; bot.get_guild.return_value = guild
    with (_runtime_policy(123), patch("services.discord_admin_service.discord.TextChannel", new=type(channel))):
        result = await service.send_message(123, 456, "reply", reply_to_message_id=654)
    assert result["success"] is True
    kwargs = channel.send.await_args.kwargs
    assert kwargs["reference"] is original
    assert kwargs["mention_author"] is False
    assert kwargs["allowed_mentions"].replied_user is False


@pytest.mark.asyncio
async def test_send_message_can_quote_message_content():
    service, bot = _service_with_bot()
    guild = MagicMock(); guild.id = 123
    channel = MagicMock(); channel.id = 456
    quoted = SimpleNamespace(id=654, content="first line\nsecond line", author=SimpleNamespace(display_name="Yuta"))
    channel.fetch_message = AsyncMock(return_value=quoted)
    channel.send = AsyncMock(return_value=SimpleNamespace(id=789))
    guild.get_channel.return_value = channel; bot.get_guild.return_value = guild
    with (_runtime_policy(123), patch("services.discord_admin_service.discord.TextChannel", new=type(channel))):
        result = await service.send_message(123, 456, "my response", quote_message_id=654)
    assert result["success"] is True
    assert result["content"] == "> **Yuta:**\n> first line\n> second line\n\nmy response"
    assert channel.send.await_args.kwargs["reference"] is None


@pytest.mark.asyncio
async def test_delete_message_does_not_forward_unsupported_reason():
    service, bot = _service_with_bot()
    guild = MagicMock(); guild.id = 123; guild.name = "Test"
    channel = MagicMock(); channel.id = 456
    message = SimpleNamespace(id=789, delete=AsyncMock())
    channel.fetch_message = AsyncMock(return_value=message)
    guild.get_channel.return_value = channel; bot.get_guild.return_value = guild

    with (
        _runtime_policy(123),
        patch("services.discord_admin_service.discord.TextChannel", new=type(channel)),
    ):
        result = await service.delete_message(123, 456, 789, "cleanup")

    assert result["success"] is True
    channel.fetch_message.assert_awaited_once_with(789)
    message.delete.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_disallowed_guild_cannot_be_mutated():
    service, bot = _service_with_bot()
    bot.get_guild.return_value = MagicMock()

    with _runtime_policy(123):
        result = await service.timeout_member(999, 111, 60, "test")

    assert result["success"] is False
    assert "not enabled" in result["message"]


@pytest.mark.asyncio
async def test_list_members_uses_rest_pagination_and_exposes_nickname():
    service, bot = _service_with_bot()
    guild = MagicMock(); guild.id = 123; guild.name = "Test"
    bot.get_guild.return_value = guild

    role_default = SimpleNamespace(id=1, name="@everyone", is_default=lambda: True)
    role_member = SimpleNamespace(id=2, name="Member", is_default=lambda: False)
    members = [
        SimpleNamespace(
            id=10, name="one", display_name="One", global_name="One", nick="Guild One",
            bot=False, roles=[role_default, role_member], timed_out_until=None,
        ),
        SimpleNamespace(
            id=20, name="bot", display_name="Bot", global_name=None, nick=None,
            bot=True, roles=[role_default], timed_out_until=None,
        ),
    ]

    async def fetch_members(*, limit, after=None):
        assert limit == 2
        assert after is None
        for member in members:
            yield member

    guild.fetch_members = fetch_members

    with _runtime_policy(123):
        result = await service.list_members(123, limit=2, include_bots=False)

    assert result["success"] is True
    assert result["count"] == 1
    assert result["fetched_count"] == 2
    assert result["next_after_user_id"] == 20
    assert result["members"][0]["nickname"] == "Guild One"
    assert result["members"][0]["roles"] == [{"id": 2, "name": "Member"}]


@pytest.mark.asyncio
async def test_list_members_passes_after_cursor_to_discord():
    service, bot = _service_with_bot()
    guild = MagicMock(); guild.id = 123; guild.name = "Test"
    bot.get_guild.return_value = guild

    async def fetch_members(*, limit, after=None):
        assert limit == 50
        assert after is not None
        assert after.id == 987654321
        if False:
            yield None

    guild.fetch_members = fetch_members

    with _runtime_policy(123):
        result = await service.list_members(123, after_user_id=987654321)

    assert result["success"] is True
    assert result["members"] == []
    assert result["next_after_user_id"] is None


@pytest.mark.asyncio
async def test_list_members_fails_clearly_when_members_intent_is_disabled():
    service, bot = _service_with_bot()
    bot.intents.members = False
    guild = MagicMock(); guild.id = 123; guild.name = "Test"
    bot.get_guild.return_value = guild

    with _runtime_policy(123):
        result = await service.list_members(123)

    assert result["success"] is False
    assert result["code"] == "members_intent_disabled"
    assert "DISCORD_MEMBERS_INTENT=true" in result["hint"]


@pytest.mark.asyncio
async def test_list_channels_can_fold_active_threads_into_channel_discovery():
    service, bot = _service_with_bot()
    guild = MagicMock(); guild.id = 123; guild.name = "Test"
    text = SimpleNamespace(id=10, name="general", type="text", category_id=None, position=0)
    thread = SimpleNamespace(
        id=20, name="topic", type="public_thread", category_id=None,
        position=None, parent_id=10, archived=False, locked=False,
    )
    guild.channels = [text]
    guild.threads = [thread]
    bot.get_guild.return_value = guild

    with _runtime_policy(123):
        result = await service.list_channels(123, include_threads=True)

    assert result["success"] is True
    assert [item["id"] for item in result["channels"]] == [10, 20]
    assert result["channels"][1]["parent_id"] == 10


@pytest.mark.asyncio
async def test_direct_message_listing_exposes_existing_conversations():
    service, bot = _service_with_bot()
    recipient = SimpleNamespace(id=42, display_name="Yuta", bot=False)
    channel = MagicMock(); channel.id = 500; channel.recipient = recipient; channel.last_message_id = 900
    bot.private_channels = [channel]

    with patch("services.discord_admin_service.discord.DMChannel", new=type(channel)):
        result = await service.direct_messages()

    assert result["success"] is True
    assert result["count"] == 1
    assert result["conversations"][0]["user"]["id"] == 42
    assert result["conversations"][0]["last_message_id"] == 900


@pytest.mark.asyncio
async def test_send_direct_message_replies_to_existing_dm_without_guild_scope():
    service, bot = _service_with_bot()
    recipient = SimpleNamespace(id=42, display_name="Yuta", bot=False)
    channel = MagicMock(); channel.id = 500; channel.recipient = recipient
    channel.send = AsyncMock(return_value=SimpleNamespace(id=901))
    bot.private_channels = [channel]

    with patch("services.discord_admin_service.discord.DMChannel", new=type(channel)):
        result = await service.send_direct_message(42, "hello")

    assert result["success"] is True
    assert result["user_id"] == 42
    kwargs = channel.send.await_args.kwargs
    assert kwargs["allowed_mentions"].everyone is False
    assert kwargs["allowed_mentions"].users is False
    assert kwargs["allowed_mentions"].roles is False


@pytest.mark.asyncio
async def test_send_direct_message_rejects_arbitrary_new_user():
    service, bot = _service_with_bot()
    bot.private_channels = []
    bot.guilds = []

    with patch.dict(os.environ, {"DISCORD_MCP_DM_USER_IDS": ""}, clear=False):
        result = await service.send_direct_message(999, "hello")

    assert result["success"] is False
    assert result["code"] == "dm_target_not_allowed"
    bot.fetch_user.assert_not_called()


@pytest.mark.asyncio
async def test_send_direct_message_allows_explicit_deployment_user():
    service, bot = _service_with_bot()
    bot.private_channels = []
    bot.guilds = []
    channel = MagicMock(); channel.id = 500; channel.send = AsyncMock(return_value=SimpleNamespace(id=901))
    user = MagicMock(); user.id = 42; user.dm_channel = channel
    bot.get_user.return_value = user

    with patch.dict(os.environ, {"DISCORD_MCP_DM_USER_IDS": "42"}, clear=False):
        result = await service.send_direct_message(42, "hello")

    assert result["success"] is True
    channel.send.assert_awaited_once()
