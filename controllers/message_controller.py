"""Discord message bridge with explicit trust boundaries."""

from __future__ import annotations

import logging
import os
from urllib.parse import urlparse

import discord
from discord.ext import commands

from services.concurrency_manager import ConcurrencyManager, UserRateLimiter
from services.lily_core_service import LilyCoreService
from services.session_service import SessionLimitExceeded, SessionService
from utils.message_utils import send_message

logger = logging.getLogger("lily-discord-adapter")


def _id_allowlist_from_env(name: str) -> frozenset[int]:
    values: set[int] = set()
    for raw in os.getenv(name, "").split(","):
        raw = raw.strip()
        if not raw:
            continue
        try:
            value = int(raw)
        except ValueError:
            logger.warning("Ignoring invalid %s entry: %s", name, raw)
            continue
        if value > 0:
            values.add(value)
    return frozenset(values)


def _trusted_discord_attachment(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    host = parsed.hostname.lower().rstrip(".")
    return (
        host in {"cdn.discordapp.com", "media.discordapp.net"}
        or host.endswith(".discordapp.com")
        or host.endswith(".discordapp.net")
    )


class MessageController:
    """Bridge only explicitly trusted Discord contexts into Lily-Core.

    This policy is deliberately separate from the MCP guild policy. A guild may
    remain fully administrable over authenticated MCP while its members are not
    allowed to feed arbitrary text into Lily-Core.
    """

    def __init__(
        self,
        bot: commands.Bot,
        session_service: SessionService,
        lily_core_service: LilyCoreService,
        concurrency_manager: ConcurrencyManager | None = None,
        user_rate_limiter: UserRateLimiter | None = None,
        *,
        allowed_chat_guild_ids: frozenset[int] | set[int] | None = None,
        allowed_chat_channel_ids: frozenset[int] | set[int] | None = None,
    ):
        self.bot = bot
        self.session_service = session_service
        self.lily_core_service = lily_core_service
        self.concurrency_manager = concurrency_manager
        self.user_rate_limiter = user_rate_limiter
        self.allowed_chat_guild_ids = frozenset(
            allowed_chat_guild_ids
            if allowed_chat_guild_ids is not None
            else _id_allowlist_from_env("DISCORD_CHAT_GUILD_IDS")
        )
        self.allowed_chat_channel_ids = frozenset(
            allowed_chat_channel_ids
            if allowed_chat_channel_ids is not None
            else _id_allowlist_from_env("DISCORD_CHAT_CHANNEL_IDS")
        )
        self._user_sessions: dict[str, object] = {}
        bot.event(self.on_message)

    def _context(self, message: discord.Message) -> tuple[int, int, str] | None:
        guild = getattr(message, "guild", None)
        channel = getattr(message, "channel", None)
        author = getattr(message, "author", None)
        guild_id = getattr(guild, "id", None)
        channel_id = getattr(channel, "id", None)
        user_id = getattr(author, "id", None)
        if not all(isinstance(value, int) and value > 0 for value in (guild_id, channel_id, user_id)):
            return None
        return guild_id, channel_id, str(user_id)

    def _chat_context_allowed(self, message: discord.Message) -> bool:
        context = self._context(message)
        if context is None:
            return False
        guild_id, channel_id, _ = context
        if guild_id not in self.allowed_chat_guild_ids:
            return False
        return not self.allowed_chat_channel_ids or channel_id in self.allowed_chat_channel_ids

    def _scope(self, message: discord.Message) -> tuple[str, str, str] | None:
        context = self._context(message)
        if context is None:
            return None
        guild_id, channel_id, user_id = context
        # Conversation memory is isolated per guild + channel + user. Rate limits
        # are per guild + user so changing channels cannot refill a bucket.
        core_user_id = f"discord:{guild_id}:{channel_id}:{user_id}"
        session_key = core_user_id
        rate_key = f"discord:{guild_id}:{user_id}"
        return session_key, core_user_id, rate_key

    async def on_message(self, message: discord.Message):
        # Never let another bot manufacture Lily sessions or consume the queue.
        if getattr(message.author, "bot", False):
            return

        # Discord-native commands/addons are independent from Lily-Core chat trust.
        await self.bot.process_commands(message)

        if not message.content.startswith(self.bot.command_prefix):
            await self.handle_user_message(message)

    async def handle_user_message(self, message: discord.Message):
        if not self._chat_context_allowed(message):
            return

        scope = self._scope(message)
        if scope is None:
            return
        session_key, core_user_id, rate_key = scope
        username = message.author.name
        content = message.content.strip()
        channel = message.channel

        if self.user_rate_limiter and not await self.user_rate_limiter.acquire(rate_key):
            logger.warning("Discord user rate limit exceeded for %s", rate_key)
            await channel.send("You're sending messages too fast! Please slow down.")
            return

        if self.session_service.is_wake_phrase(content):
            await self._handle_wake_phrase(
                session_key, core_user_id, username, content, channel, message
            )
            return

        if self.session_service.is_goodbye_phrase(content):
            await self._handle_goodbye_phrase(
                session_key, core_user_id, username, content, channel
            )
            return

        if not self.session_service.is_session_active(session_key):
            if content.lower().startswith("hey"):
                await channel.send("Hi! Say **'Hey Lily'** to wake me up and start a conversation.")
            return

        await self._handle_chat_message(
            session_key, core_user_id, username, content, channel, message
        )

    async def _submit_or_send(
        self,
        *,
        core_user_id: str,
        username: str,
        content: str,
        channel,
        attachments: list[dict] | None = None,
    ) -> None:
        attachments = attachments or []
        if self.concurrency_manager:
            success = await self.concurrency_manager.submit_message(
                {
                    "user_id": core_user_id,
                    "username": username,
                    "text": content,
                    "channel": channel,
                    "attachments": attachments,
                }
            )
            if not success:
                await channel.send("Message queue is full. Please try again.")
            return

        response_text = await self.lily_core_service.send_chat_message(
            core_user_id, username, content, attachments
        )
        if response_text:
            await send_message(channel, response_text, prefix="")

    async def _handle_wake_phrase(
        self,
        session_key: str,
        core_user_id: str,
        username: str,
        content: str,
        channel,
        message: discord.Message,
    ):
        try:
            self.session_service.create_session(session_key, username, channel)
        except SessionLimitExceeded:
            logger.warning("Discord session capacity reached")
            await channel.send("Lily is at session capacity. Please try again later.")
            return

        actual_message = self.session_service.extract_message_after_wake(content)
        await self._submit_or_send(
            core_user_id=core_user_id,
            username=username,
            content=actual_message,
            channel=channel,
            attachments=[],
        )
        logger.info("Trusted Discord Lily session started for %s", session_key)

    async def _handle_goodbye_phrase(
        self,
        session_key: str,
        core_user_id: str,
        username: str,
        content: str,
        channel,
    ):
        if not self.session_service.is_session_active(session_key):
            return
        self.session_service.end_session(session_key)
        await self._submit_or_send(
            core_user_id=core_user_id,
            username=username,
            content=content,
            channel=channel,
        )
        logger.info("Trusted Discord Lily session ended for %s", session_key)

    async def _handle_chat_message(
        self,
        session_key: str,
        core_user_id: str,
        username: str,
        content: str,
        channel,
        message: discord.Message,
    ):
        self._user_sessions[session_key] = channel
        attachments = []
        for attachment in message.attachments[:4]:
            filename = attachment.filename.lower()
            if not filename.endswith((".wav", ".mp3", ".m4a", ".flac", ".ogg")):
                continue
            if not _trusted_discord_attachment(attachment.url):
                logger.warning("Discarding untrusted Discord attachment URL")
                continue
            attachments.append(
                {
                    "type": "audio",
                    "url": attachment.url,
                    "filename": attachment.filename,
                }
            )

        await self._submit_or_send(
            core_user_id=core_user_id,
            username=username,
            content=content,
            channel=channel,
            attachments=attachments,
        )
        # Do not log attacker-controlled message bodies.
        logger.info("Processed trusted Discord message for %s (%s chars)", session_key, len(content))

    def get_channel_for_user(self, user_id: str):
        return self._user_sessions.get(user_id)

    def update_user_channel(self, user_id: str, channel):
        self._user_sessions[user_id] = channel
