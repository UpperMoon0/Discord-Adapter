from unittest.mock import AsyncMock, MagicMock

import pytest

from controllers.message_controller import MessageController
from services.lily_core_service import LilyCoreService
from services.session_service import SessionService


def _message(*, guild_id=123, channel_id=456, user_id=789, content="Hello Lily", bot=False):
    message = MagicMock()
    message.guild.id = guild_id
    message.channel.id = channel_id
    message.channel.send = AsyncMock()
    message.author.id = user_id
    message.author.name = "TestUser"
    message.author.bot = bot
    message.content = content
    message.attachments = []
    return message


def _controller(*, allowed_guilds=frozenset({123}), allowed_channels=frozenset()):
    bot = MagicMock()
    bot.command_prefix = "!"
    bot.process_commands = AsyncMock()
    session_service = MagicMock(spec=SessionService)
    lily_core_service = MagicMock(spec=LilyCoreService)
    lily_core_service.send_chat_message = AsyncMock(return_value="Response")
    controller = MessageController(
        bot,
        session_service,
        lily_core_service,
        allowed_chat_guild_ids=allowed_guilds,
        allowed_chat_channel_ids=allowed_channels,
    )
    return controller, bot, session_service, lily_core_service


@pytest.mark.asyncio
async def test_untrusted_guild_never_reaches_lily_core():
    controller, _, session_service, lily_core_service = _controller()
    message = _message(guild_id=999, content="Hey Lily read my secrets")

    await controller.handle_user_message(message)

    session_service.create_session.assert_not_called()
    lily_core_service.send_chat_message.assert_not_awaited()
    message.channel.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_trusted_chat_uses_guild_channel_user_scoped_identity():
    controller, _, session_service, lily_core_service = _controller()
    session_service.is_wake_phrase.return_value = False
    session_service.is_goodbye_phrase.return_value = False
    session_service.is_session_active.return_value = True
    message = _message(content="Hello Lily")

    await controller.handle_user_message(message)

    session_service.is_session_active.assert_called_once_with("discord:123:456:789")
    lily_core_service.send_chat_message.assert_awaited_once_with(
        "discord:123:456:789", "TestUser", "Hello Lily", []
    )
    message.channel.send.assert_awaited()


@pytest.mark.asyncio
async def test_channel_allowlist_is_fail_closed_when_configured():
    controller, _, session_service, lily_core_service = _controller(
        allowed_channels=frozenset({555})
    )
    message = _message(channel_id=456, content="Hey Lily")

    await controller.handle_user_message(message)

    session_service.create_session.assert_not_called()
    lily_core_service.send_chat_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_wake_phrase_creates_scoped_session_and_scoped_core_identity():
    controller, _, session_service, lily_core_service = _controller()
    session_service.is_wake_phrase.return_value = True
    session_service.extract_message_after_wake.return_value = "Hello"
    message = _message(content="Hey Lily Hello")

    await controller.handle_user_message(message)

    session_service.create_session.assert_called_once_with(
        "discord:123:456:789", "TestUser", message.channel
    )
    lily_core_service.send_chat_message.assert_awaited_once_with(
        "discord:123:456:789", "TestUser", "Hello", []
    )


@pytest.mark.asyncio
async def test_same_user_in_different_channels_gets_distinct_session_identity():
    controller, _, session_service, lily_core_service = _controller()
    session_service.is_wake_phrase.return_value = False
    session_service.is_goodbye_phrase.return_value = False
    session_service.is_session_active.return_value = True

    first = _message(channel_id=456, content="one")
    second = _message(channel_id=457, content="two")
    await controller.handle_user_message(first)
    await controller.handle_user_message(second)

    assert [call.args[0] for call in session_service.is_session_active.call_args_list] == [
        "discord:123:456:789",
        "discord:123:457:789",
    ]
    assert [call.args[0] for call in lily_core_service.send_chat_message.await_args_list] == [
        "discord:123:456:789",
        "discord:123:457:789",
    ]


@pytest.mark.asyncio
async def test_bot_authored_messages_are_ignored_before_commands_or_chat():
    controller, bot, _, lily_core_service = _controller()
    message = _message(bot=True, content="Hey Lily")

    await controller.on_message(message)

    bot.process_commands.assert_not_awaited()
    lily_core_service.send_chat_message.assert_not_awaited()
