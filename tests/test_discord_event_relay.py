import asyncio
import hashlib
import hmac
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from services.discord_event_relay import DiscordEventRelay, EventRelayConfig


def _config():
    return EventRelayConfig(
        url="https://automation.example.org/discord-events",
        secret="test-secret-of-at-least-32-characters",
        guild_ids=frozenset({123}),
        channel_ids=frozenset({456}),
        user_ids=frozenset({789}),
    )


def _message(*, guild=123, channel=456, user=789, message_id=1000, bot=False):
    return SimpleNamespace(
        id=message_id,
        guild=SimpleNamespace(id=guild),
        channel=SimpleNamespace(id=channel),
        author=SimpleNamespace(id=user, bot=bot),
        content="Need help connecting",
        attachments=[SimpleNamespace(filename="error.png", url="https://cdn.discordapp.com/a.png")],
    )


def test_disabled_without_explicit_webhook(monkeypatch):
    monkeypatch.delenv("DISCORD_EVENT_WEBHOOK_URL", raising=False)
    assert EventRelayConfig.from_env() is None


def test_relay_from_env_disables_invalid_optional_configuration(monkeypatch, caplog):
    monkeypatch.setenv("DISCORD_EVENT_WEBHOOK_URL", "https://automation.example.org/events")
    monkeypatch.delenv("DISCORD_EVENT_WEBHOOK_SECRET", raising=False)
    monkeypatch.delenv("DISCORD_EVENT_GUILD_IDS", raising=False)
    monkeypatch.delenv("DISCORD_EVENT_CHANNEL_IDS", raising=False)

    relay = DiscordEventRelay.from_env()

    assert relay.enabled is False
    assert relay.config is None
    assert "event relay disabled due to invalid configuration" in caplog.text.lower()


def test_event_config_is_fail_closed(monkeypatch):
    monkeypatch.setenv("DISCORD_EVENT_WEBHOOK_URL", "http://localhost/events")
    with pytest.raises(ValueError, match="HTTPS"):
        EventRelayConfig.from_env()
    monkeypatch.setenv("DISCORD_EVENT_WEBHOOK_URL", "https://automation.example.org/events")
    monkeypatch.setenv("DISCORD_EVENT_WEBHOOK_SECRET", "short")
    with pytest.raises(ValueError, match="32 bytes"):
        EventRelayConfig.from_env()
    monkeypatch.setenv("DISCORD_EVENT_WEBHOOK_SECRET", "a" * 32)
    with pytest.raises(ValueError, match="allowlists"):
        EventRelayConfig.from_env()
    monkeypatch.setenv("DISCORD_EVENT_GUILD_IDS", "123")
    monkeypatch.setenv("DISCORD_EVENT_CHANNEL_IDS", "456")
    monkeypatch.setenv("DISCORD_EVENT_USER_IDS", "789")
    conf = EventRelayConfig.from_env()
    assert conf.guild_ids == {123}
    assert conf.user_ids == {789}


@pytest.mark.asyncio
async def test_publishes_scoped_hmac_signed_event_once_with_string_ids():
    sender = AsyncMock(return_value=202)
    relay = DiscordEventRelay(_config(), guild_allowed=lambda guild: guild == 123, sender=sender)
    assert await relay.observe(_message()) is True
    assert await relay.observe(_message()) is False
    await asyncio.wait_for(relay._queue.join(), timeout=1)
    sender.assert_awaited_once()
    url, body, headers = sender.await_args.args
    assert url.startswith("https://")
    event = json.loads(body)
    assert event == {
        "event_type": "discord.message.created",
        "version": 1,
        "event_id": "1000",
        "guild_id": "123",
        "channel_id": "456",
        "user_id": "789",
        "content": "Need help connecting",
        "attachments": [{"filename": "error.png", "url": "https://cdn.discordapp.com/a.png"}],
    }
    assert headers["X-Discord-Event-ID"] == "1000"
    signed = headers["X-Discord-Event-Timestamp"].encode() + b"." + body
    expected = hmac.new(_config().secret.encode(), signed, hashlib.sha256).hexdigest()
    assert headers["X-Discord-Event-Signature"] == "sha256=" + expected
    assert relay.delivered == 1
    await relay.close()


@pytest.mark.asyncio
async def test_filters_bots_wrong_users_guilds_and_channels_without_network():
    sender = AsyncMock(return_value=202)
    relay = DiscordEventRelay(_config(), guild_allowed=lambda guild: guild == 123, sender=sender)
    for kwargs in ({"bot": True}, {"guild": 999}, {"channel": 999}, {"user": 999}):
        assert await relay.observe(_message(**kwargs)) is False
    assert relay.status()["queued"] == 0
    sender.assert_not_awaited()
    await relay.close()


@pytest.mark.asyncio
async def test_revocation_before_delivery_suppresses_outbound_webhook():
    allowed = True
    sender = AsyncMock(return_value=202)
    relay = DiscordEventRelay(_config(), guild_allowed=lambda _: allowed, sender=sender)
    assert await relay.observe(_message()) is True
    allowed = False
    await asyncio.wait_for(relay._queue.join(), timeout=1)
    sender.assert_not_awaited()
    assert relay.dropped == 1
    await relay.close()


@pytest.mark.asyncio
async def test_http_failure_retries_but_never_posts_to_discord():
    sender = AsyncMock(side_effect=[503, 429, 204])
    relay = DiscordEventRelay(_config(), guild_allowed=lambda _: True, sender=sender)
    with patch("services.discord_event_relay.asyncio.sleep", new_callable=AsyncMock):
        assert await relay.observe(_message()) is True
        await asyncio.wait_for(relay._queue.join(), timeout=1)
    assert sender.await_count == 3
    assert relay.delivered == 1
    await relay.close()


@pytest.mark.asyncio
async def test_4xx_is_not_retried():
    sender = AsyncMock(return_value=403)
    relay = DiscordEventRelay(_config(), guild_allowed=lambda _: True, sender=sender)
    assert await relay.observe(_message()) is True
    await asyncio.wait_for(relay._queue.join(), timeout=1)
    assert sender.await_count == 1
    assert relay.failed == 1
    await relay.close()
