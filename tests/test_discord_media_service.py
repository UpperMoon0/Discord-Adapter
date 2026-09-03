from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mcp.types import ImageContent, TextContent

from services.discord_media_service import DiscordMediaService


class _AdminHarness:
    def __init__(self, guild, channel):
        self.guild = guild
        self.channel = channel

    def _guild(self, guild_id):
        assert guild_id == self.guild.id
        return self.guild, None

    def _channel(self, guild, channel_id):
        assert guild is self.guild
        assert channel_id == self.channel.id
        return self.channel

    async def _run(self, operation):
        return await operation()


def _attachment(**overrides):
    values = {
        "id": 9001,
        "filename": "picture.png",
        "content_type": "image/png",
        "size": 8,
        "width": 320,
        "height": 200,
        "duration": None,
        "description": None,
        "url": "https://cdn.discordapp.com/attachments/1/2/picture.png",
        "proxy_url": "https://media.discordapp.net/attachments/1/2/picture.png",
        "is_spoiler": lambda: False,
        "read": AsyncMock(return_value=b"fake-png"),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.asyncio
async def test_list_message_media_exposes_attachment_metadata_and_index():
    guild = SimpleNamespace(id=123)
    channel = MagicMock()
    channel.id = 456
    message = SimpleNamespace(
        id=789,
        jump_url="https://discord.com/channels/123/456/789",
        attachments=[_attachment()],
        embeds=[],
    )
    channel.fetch_message = AsyncMock(return_value=message)
    service = DiscordMediaService(_AdminHarness(guild, channel))

    with patch("services.discord_media_service.discord.TextChannel", new=type(channel)):
        result = await service.list_message_media(123, 456, 789)

    assert result["success"] is True
    assert result["count"] == 1
    media = result["media"][0]
    assert media["media_index"] == 0
    assert media["attachment_id"] == 9001
    assert media["content_type"] == "image/png"
    assert media["inspectable"] is True


@pytest.mark.asyncio
async def test_read_message_media_returns_actual_mcp_image_content():
    guild = SimpleNamespace(id=123)
    channel = MagicMock()
    channel.id = 456
    attachment = _attachment()
    message = SimpleNamespace(
        id=789,
        jump_url="https://discord.com/channels/123/456/789",
        attachments=[attachment],
        embeds=[],
    )
    channel.fetch_message = AsyncMock(return_value=message)
    service = DiscordMediaService(_AdminHarness(guild, channel))

    with patch("services.discord_media_service.discord.TextChannel", new=type(channel)):
        result = await service.read_message_media(123, 456, 789)

    assert isinstance(result[0], TextContent)
    assert isinstance(result[1], ImageContent)
    assert result[1].mime_type == "image/png"
    attachment.read.assert_awaited_once_with(use_cached=True)


@pytest.mark.asyncio
async def test_read_message_media_rejects_oversized_attachment_before_download():
    guild = SimpleNamespace(id=123)
    channel = MagicMock()
    channel.id = 456
    attachment = _attachment(size=10_000)
    message = SimpleNamespace(
        id=789,
        jump_url="https://discord.com/channels/123/456/789",
        attachments=[attachment],
        embeds=[],
    )
    channel.fetch_message = AsyncMock(return_value=message)
    service = DiscordMediaService(_AdminHarness(guild, channel))
    service.max_download_bytes = 100

    with patch("services.discord_media_service.discord.TextChannel", new=type(channel)):
        result = await service.read_message_media(123, 456, 789)

    assert isinstance(result[0], TextContent)
    assert "too large" in result[0].text
    attachment.read.assert_not_awaited()


def test_embed_fetching_only_accepts_expected_media_hosts():
    service = DiscordMediaService(MagicMock())

    assert service._trusted_media_url("https://media.discordapp.net/external/x/file.gif")
    assert service._trusted_media_url("https://media.tenor.com/foo.gif")
    assert not service._trusted_media_url("http://media.discordapp.net/file.png")
    assert not service._trusted_media_url("https://untrusted.invalid/file.png")
