"""Opt-in, one-way Discord Gateway event relay for external automation.

This forwards tightly scoped message-created events to an administrator-owned
HTTPS webhook. It is not a native ChatGPT Work task trigger, and never sends
messages to Discord. Disabled unless every required setting is configured.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
from collections import deque
from dataclasses import dataclass
from typing import Awaitable, Callable
from urllib.parse import urlsplit

import httpx

from services.access_policy_service import access_policy_service

logger = logging.getLogger("lily-discord-adapter")


def _ids_env(name: str) -> frozenset[int]:
    values: set[int] = set()
    for item in os.getenv(name, "").split(","):
        item = item.strip()
        if not item:
            continue
        if not item.isascii() or not item.isdecimal() or int(item) <= 0:
            raise ValueError(f"{name} contains an invalid Discord ID")
        values.add(int(item))
    return frozenset(values)


@dataclass(frozen=True)
class EventRelayConfig:
    url: str
    secret: str
    guild_ids: frozenset[int]
    channel_ids: frozenset[int]
    user_ids: frozenset[int]

    @classmethod
    def from_env(cls) -> "EventRelayConfig | None":
        url = os.getenv("DISCORD_EVENT_WEBHOOK_URL", "").strip()
        if not url:
            return None
        parsed = urlsplit(url)
        if (
            len(url) > 2048 or parsed.scheme != "https" or not parsed.hostname
            or parsed.username or parsed.password or parsed.fragment
        ):
            raise ValueError("DISCORD_EVENT_WEBHOOK_URL must be an HTTPS URL without credentials or fragments")
        secret = os.getenv("DISCORD_EVENT_WEBHOOK_SECRET", "")
        if len(secret.encode("utf-8")) < 32:
            raise ValueError("DISCORD_EVENT_WEBHOOK_SECRET must contain at least 32 bytes")
        guild_ids = _ids_env("DISCORD_EVENT_GUILD_IDS")
        channel_ids = _ids_env("DISCORD_EVENT_CHANNEL_IDS")
        user_ids = _ids_env("DISCORD_EVENT_USER_IDS")
        if not guild_ids or not channel_ids:
            raise ValueError("Event relay requires nonempty guild and channel allowlists")
        return cls(url=url, secret=secret, guild_ids=guild_ids, channel_ids=channel_ids, user_ids=user_ids)


class DiscordEventRelay:
    """Forward scoped new-message events without blocking Discord message handling."""

    def __init__(
        self,
        config: EventRelayConfig | None = None,
        *,
        guild_allowed: Callable[[int], bool] = access_policy_service.is_guild_allowed,
        sender: Callable[[str, bytes, dict[str, str]], Awaitable[int]] | None = None,
    ):
        self.config = config
        self.guild_allowed = guild_allowed
        self.sender = sender or self._http_post
        self._queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=256)
        self._worker: asyncio.Task | None = None
        self._recent_ids: set[int] = set()
        self._recent_order: deque[int] = deque()
        self._closed = False
        self.delivered = 0
        self.dropped = 0
        self.failed = 0

    @classmethod
    def from_env(cls) -> "DiscordEventRelay":
        return cls(EventRelayConfig.from_env())

    @property
    def enabled(self) -> bool:
        return self.config is not None and not self._closed

    async def observe(self, message) -> bool:
        """Queue one Discord user message if its guild/channel/author are allowed."""
        if not self.enabled or getattr(message.author, "bot", False):
            return False
        guild_id = getattr(getattr(message, "guild", None), "id", None)
        channel_id = getattr(getattr(message, "channel", None), "id", None)
        user_id = getattr(getattr(message, "author", None), "id", None)
        message_id = getattr(message, "id", None)
        if not all(type(x) is int and x > 0 for x in (guild_id, channel_id, user_id, message_id)):
            return False
        assert self.config is not None
        if (
            guild_id not in self.config.guild_ids
            or channel_id not in self.config.channel_ids
            or (self.config.user_ids and user_id not in self.config.user_ids)
            or not self.guild_allowed(guild_id)
            or message_id in self._recent_ids
        ):
            return False

        event = {
            "event_type": "discord.message.created",
            "version": 1,
            "event_id": str(message_id),
            "guild_id": str(guild_id),
            "channel_id": str(channel_id),
            "user_id": str(user_id),
            "content": str(getattr(message, "content", ""))[:2000],
            "attachments": [
                {"filename": str(getattr(a, "filename", ""))[:120], "url": str(getattr(a, "url", ""))[:2048]}
                for a in (getattr(message, "attachments", []) or [])[:4]
            ],
        }
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            self.dropped += 1
            logger.warning("Discord event relay queue full; dropped an event")
            return False
        self._recent_ids.add(message_id)
        self._recent_order.append(message_id)
        if len(self._recent_order) > 2048:
            self._recent_ids.discard(self._recent_order.popleft())
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._drain())
        return True

    @staticmethod
    async def _http_post(url: str, body: bytes, headers: dict[str, str]) -> int:
        # URL is administrator configuration, never text from a Discord user.
        async with httpx.AsyncClient(timeout=5.0, follow_redirects=False, trust_env=False) as client:
            response = await client.post(url, content=body, headers=headers)
            return response.status_code

    async def _deliver(self, event: dict) -> None:
        assert self.config is not None
        # Recheck the mutable Redis allowlist immediately before network delivery.
        if not self.guild_allowed(int(event["guild_id"])):
            self.dropped += 1
            return
        body = json.dumps(event, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        signature = hmac.new(self.config.secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        headers = {
            "Content-Type": "application/json",
            "X-Discord-Event-ID": event["event_id"],
            "X-Discord-Event-Signature": f"sha256={signature}",
        }
        for attempt in range(3):
            try:
                status = await self.sender(self.config.url, body, headers)
            except (httpx.HTTPError, TimeoutError, OSError) as exc:
                logger.warning("Discord event relay transport failure: %s", type(exc).__name__)
                status = 503
            if 200 <= status < 300:
                self.delivered += 1
                return
            if (status != 429 and status < 500) or attempt == 2:
                break
            await asyncio.sleep(0.5 * (2**attempt))
        self.failed += 1
        logger.warning("Discord event relay delivery failed; event_id=%s", event["event_id"])

    async def _drain(self) -> None:
        while True:
            event = await self._queue.get()
            try:
                await self._deliver(event)
            except Exception:
                self.failed += 1
                logger.exception("Discord event relay delivery failed unexpectedly")
            finally:
                self._queue.task_done()

    async def close(self) -> None:
        self._closed = True
        if self._worker is not None:
            try:
                await asyncio.wait_for(self._queue.join(), timeout=2.0)
            except asyncio.TimeoutError:
                pass
            self._worker.cancel()
            await asyncio.gather(self._worker, return_exceptions=True)
            self._worker = None

    def status(self) -> dict:
        return {
            "enabled": self.enabled,
            "queued": self._queue.qsize(),
            "delivered": self.delivered,
            "failed": self.failed,
            "dropped": self.dropped,
        }
