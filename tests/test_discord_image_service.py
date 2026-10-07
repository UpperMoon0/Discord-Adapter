import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.discord_image_service import DiscordImageService, decode_image


_PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"x" * 24).decode("ascii")


class AdminHarness:
    def __init__(self):
        self.guild = MagicMock()
        self.guild.id = 123
        self.channel = MagicMock()
        self.channel.id = 456
        self.channel.fetch_message = AsyncMock(return_value=SimpleNamespace(id=321))
        self.channel.send = AsyncMock(return_value=SimpleNamespace(
            id=789, jump_url="https://discord.com/channels/123/456/789"
        ))
        self.guild.get_channel.return_value = self.channel
        self.bot_calls = 0

    def _guild(self, guild_id):
        self.bot_calls += 1
        if guild_id != 123:
            return None, {"success": False, "message": "Guild is not enabled"}
        return self.guild, None

    def _channel(self, guild, channel_id):
        assert guild is self.guild
        return self.channel if channel_id == 456 else None

    async def _run(self, operation):
        return await operation()


@pytest.mark.asyncio
async def test_upload_is_real_discord_file_without_mentions_or_reply_ping():
    admin = AdminHarness()
    service = DiscordImageService(admin)
    with patch("services.discord_image_service.discord.TextChannel", new=type(admin.channel)):
        result = await service.send_image(123, 456, _PNG, caption="Image @everyone <@123>", reply_to_message_id=321)
    assert result["success"] is True
    assert result["message_id"] == 789
    assert result["jump_url"].endswith("/789")
    assert result["size_bytes"] == 32
    kwargs = admin.channel.send.await_args.kwargs
    assert kwargs["file"].filename == "image.png"
    assert kwargs["content"] == "Image @everyone <@123>"
    assert kwargs["allowed_mentions"].everyone is False
    assert kwargs["allowed_mentions"].users is False
    assert kwargs["allowed_mentions"].roles is False
    assert kwargs["allowed_mentions"].replied_user is False
    assert kwargs["mention_author"] is False
    assert kwargs["reference"].id == 321


@pytest.mark.asyncio
async def test_upload_can_send_image_without_caption():
    admin = AdminHarness()
    service = DiscordImageService(admin)
    with patch("services.discord_image_service.discord.TextChannel", new=type(admin.channel)):
        result = await service.send_image(123, 456, _PNG)
    assert result["success"] is True
    assert admin.channel.send.await_args.kwargs["content"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("name,image,error", [
    ("../../evil.png", _PNG, "safe"),
    ("bad.jpg", _PNG, "do not match"),
    ("bad.png", "#not base64#", "not valid"),
    ("bad.png", "", "must be"),
])
async def test_rejects_bad_image_before_any_discord_action(name, image, error):
    admin = AdminHarness()
    service = DiscordImageService(admin)
    result = await service.send_image(123, 456, image, filename=name)
    assert result["success"] is False
    assert error in result["message"]
    assert admin.bot_calls == 0
    admin.channel.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_oversize_image_rejected_without_discord_action():
    admin = AdminHarness()
    service = DiscordImageService(admin)
    service.max_upload_bytes = 12
    result = await service.send_image(123, 456, _PNG)
    assert result["success"] is False
    assert admin.bot_calls == 0


@pytest.mark.asyncio
async def test_guild_and_channel_scope_are_checked_before_posting():
    admin = AdminHarness()
    service = DiscordImageService(admin)
    result = await service.send_image(999, 456, _PNG)
    assert result["success"] is False
    assert admin.channel.send.await_count == 0
    with patch("services.discord_image_service.discord.TextChannel", new=type(admin.channel)):
        result = await service.send_image(123, 999, _PNG)
    assert result["success"] is False
    assert admin.channel.send.await_count == 0


def test_image_signature_must_match_extension():
    assert decode_image(_PNG, "ok.png", 1000).startswith(b"\x89PNG")
    for filename in ["test.jpeg", "test.gif", "test.webp"]:
        with pytest.raises(ValueError):
            decode_image(_PNG, filename, 1000)
