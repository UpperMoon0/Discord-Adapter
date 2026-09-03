"""Visual media inspection for Discord messages exposed through MCP."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import discord
import httpx
from mcp.types import ImageContent, TextContent

from services.discord_admin_service import DiscordAdminService, discord_admin_service

logger = logging.getLogger("lily-discord-adapter")

_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
_ANIMATED_IMAGE_EXTENSIONS = {".gif", ".apng"}
_VIDEO_EXTENSIONS = {".mp4", ".webm", ".mov", ".m4v", ".mkv"}
_DIRECT_IMAGE_MIME_TYPES = {"image/png", "image/jpeg", "image/webp"}
_DEFAULT_ALLOWED_MEDIA_HOSTS = {
    "cdn.discordapp.com",
    "media.discordapp.net",
    "media.tenor.com",
    "c.tenor.com",
    "media.giphy.com",
    "i.giphy.com",
}


def _positive_int_env(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


class DiscordMediaService:
    """Fetch and normalize visual media from one already-authorized Discord message."""

    def __init__(self, admin_service: DiscordAdminService = discord_admin_service):
        self.admin_service = admin_service
        self.max_download_bytes = _positive_int_env(
            "DISCORD_MEDIA_MAX_DOWNLOAD_BYTES", 32 * 1024 * 1024
        )
        self.max_direct_image_bytes = _positive_int_env(
            "DISCORD_MEDIA_MAX_DIRECT_IMAGE_BYTES", 6 * 1024 * 1024
        )
        self.ffmpeg_timeout_seconds = _positive_int_env(
            "DISCORD_MEDIA_FFMPEG_TIMEOUT_SECONDS", 20
        )
        configured_hosts = {
            host.strip().lower()
            for host in os.getenv("DISCORD_MEDIA_ALLOWED_HOSTS", "").split(",")
            if host.strip()
        }
        self.allowed_media_hosts = _DEFAULT_ALLOWED_MEDIA_HOSTS | configured_hosts

    @staticmethod
    def _attachment_metadata(attachment: discord.Attachment, source_index: int) -> dict:
        return {
            "source": "attachment",
            "source_index": source_index,
            "attachment_id": attachment.id,
            "filename": attachment.filename,
            "content_type": attachment.content_type,
            "size": attachment.size,
            "width": attachment.width,
            "height": attachment.height,
            "duration_seconds": getattr(attachment, "duration", None),
            "description": getattr(attachment, "description", None),
            "spoiler": attachment.is_spoiler(),
            "url": attachment.url,
            "proxy_url": attachment.proxy_url,
            "inspectable": True,
        }

    def _trusted_media_url(self, url: str | None) -> bool:
        if not url:
            return False
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname:
            return False
        host = parsed.hostname.lower().rstrip(".")
        return (
            host in self.allowed_media_hosts
            or host.endswith(".discordapp.net")
            or host.endswith(".discordapp.com")
        )

    def _embed_metadata(self, embed: discord.Embed, embed_index: int) -> list[dict]:
        items: list[dict] = []
        for part_name in ("image", "thumbnail", "video"):
            part = getattr(embed, part_name, None)
            if part is None:
                continue
            url = getattr(part, "url", None)
            proxy_url = getattr(part, "proxy_url", None)
            read_url = proxy_url if self._trusted_media_url(proxy_url) else url
            items.append(
                {
                    "source": "embed",
                    "source_index": embed_index,
                    "embed_part": part_name,
                    "filename": Path(urlparse(url or proxy_url or "media").path).name or None,
                    "content_type": None,
                    "size": None,
                    "width": getattr(part, "width", None),
                    "height": getattr(part, "height", None),
                    "duration_seconds": None,
                    "description": embed.description,
                    "url": url,
                    "proxy_url": proxy_url,
                    "read_url": read_url if self._trusted_media_url(read_url) else None,
                    "inspectable": self._trusted_media_url(read_url),
                }
            )
        return items

    def _media_candidates(self, message: discord.Message) -> list[dict]:
        candidates = [
            self._attachment_metadata(attachment, index)
            for index, attachment in enumerate(message.attachments)
        ]
        for embed_index, embed in enumerate(message.embeds):
            candidates.extend(self._embed_metadata(embed, embed_index))
        for media_index, candidate in enumerate(candidates):
            candidate["media_index"] = media_index
        return candidates

    async def _resolve_message(self, guild_id: int, channel_id: int, message_id: int):
        guild, error = self.admin_service._guild(guild_id)
        if error:
            return None, error
        channel = self.admin_service._channel(guild, channel_id)
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return None, {
                "success": False,
                "message": f"Channel {channel_id} is not a readable text channel",
            }
        message = await channel.fetch_message(message_id)
        return message, None

    async def list_message_media(self, guild_id: int, channel_id: int, message_id: int) -> dict:
        async def op() -> dict:
            message, error = await self._resolve_message(guild_id, channel_id, message_id)
            if error:
                return error
            media = self._media_candidates(message)
            return {
                "success": True,
                "guild_id": guild_id,
                "channel_id": channel_id,
                "message_id": message_id,
                "jump_url": message.jump_url,
                "media": media,
                "count": len(media),
            }

        return await self.admin_service._run(op)

    async def _download_embed(self, url: str) -> tuple[bytes, str | None]:
        if not self._trusted_media_url(url):
            raise ValueError("Media URL host is not allowlisted for server-side fetching")
        timeout = httpx.Timeout(15.0, connect=5.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            async with client.stream("GET", url) as response:
                response.raise_for_status()
                content_length = response.headers.get("content-length")
                if content_length and int(content_length) > self.max_download_bytes:
                    raise ValueError(
                        f"Media is too large ({content_length} bytes; limit {self.max_download_bytes})"
                    )
                chunks: list[bytes] = []
                total = 0
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > self.max_download_bytes:
                        raise ValueError(
                            f"Media exceeds download limit of {self.max_download_bytes} bytes"
                        )
                    chunks.append(chunk)
                return b"".join(chunks), response.headers.get("content-type")

    @staticmethod
    def _classify_media(content_type: str | None, filename: str | None) -> str:
        mime = (content_type or "").split(";", 1)[0].strip().lower()
        suffix = Path(filename or "").suffix.lower()
        if mime in {"image/gif", "image/apng"} or suffix in _ANIMATED_IMAGE_EXTENSIONS:
            return "animated_image"
        if mime.startswith("video/") or suffix in _VIDEO_EXTENSIONS:
            return "video"
        if mime.startswith("image/") or suffix in _IMAGE_EXTENSIONS:
            return "image"
        return "unsupported"

    async def _probe_duration(self, source: Path) -> float | None:
        process = await asyncio.create_subprocess_exec(
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(source),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, _ = await asyncio.wait_for(
                process.communicate(), timeout=self.ffmpeg_timeout_seconds
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.communicate()
            return None
        if process.returncode != 0:
            return None
        try:
            duration = float(json.loads(stdout.decode("utf-8"))["format"]["duration"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None
        return duration if duration > 0 else None

    async def _extract_frame(self, source: Path, target: Path, timestamp: float) -> None:
        process = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{max(timestamp, 0.0):.3f}",
            "-i",
            str(source),
            "-frames:v",
            "1",
            "-vf",
            "scale=w='min(1600,iw)':h='min(1600,ih)':force_original_aspect_ratio=decrease",
            "-q:v",
            "4",
            "-y",
            str(target),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, stderr = await asyncio.wait_for(
                process.communicate(), timeout=self.ffmpeg_timeout_seconds
            )
        except asyncio.TimeoutError as exc:
            process.kill()
            await process.communicate()
            raise ValueError("ffmpeg frame extraction timed out") from exc
        if process.returncode != 0 or not target.exists():
            detail = stderr.decode("utf-8", errors="replace").strip()[-500:]
            raise ValueError(f"ffmpeg could not extract media frame: {detail or 'unknown error'}")

    async def _frame_content(self, data: bytes, suffix: str, max_frames: int) -> list[ImageContent]:
        with tempfile.TemporaryDirectory(prefix="discord-media-") as temp_dir:
            temp = Path(temp_dir)
            source = temp / f"source{suffix or '.bin'}"
            source.write_bytes(data)
            duration = await self._probe_duration(source)
            if duration:
                timestamps = [
                    duration * (index + 0.5) / max_frames
                    for index in range(max_frames)
                ]
            else:
                timestamps = [0.0]

            frames: list[ImageContent] = []
            for index, timestamp in enumerate(timestamps):
                target = temp / f"frame-{index:02d}.jpg"
                try:
                    await self._extract_frame(source, target, timestamp)
                except ValueError:
                    if frames:
                        break
                    raise
                frames.append(
                    ImageContent(
                        type="image",
                        data=base64.b64encode(target.read_bytes()).decode("ascii"),
                        mime_type="image/jpeg",
                    )
                )
            return frames

    async def read_message_media(
        self,
        guild_id: int,
        channel_id: int,
        message_id: int,
        media_index: int = 0,
        max_frames: int = 4,
    ) -> list:
        max_frames = max(1, min(max_frames, 6))

        async def op() -> list:
            message, error = await self._resolve_message(guild_id, channel_id, message_id)
            if error:
                return [TextContent(type="text", text=json.dumps(error))]

            candidates = self._media_candidates(message)
            if not candidates:
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            {
                                "success": False,
                                "message": "Message has no image, GIF, or video media",
                                "message_id": message_id,
                            }
                        ),
                    )
                ]
            if media_index < 0 or media_index >= len(candidates):
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            {
                                "success": False,
                                "message": f"media_index must be between 0 and {len(candidates) - 1}",
                                "message_id": message_id,
                            }
                        ),
                    )
                ]

            candidate = candidates[media_index]
            if not candidate.get("inspectable"):
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            {
                                "success": False,
                                "message": "Media URL is not on the server-side fetch allowlist",
                                "media": candidate,
                            }
                        ),
                    )
                ]

            content_type = candidate.get("content_type")
            if candidate["source"] == "attachment":
                attachment = message.attachments[candidate["source_index"]]
                if attachment.size > self.max_download_bytes:
                    return [
                        TextContent(
                            type="text",
                            text=json.dumps(
                                {
                                    "success": False,
                                    "message": (
                                        f"Attachment is too large ({attachment.size} bytes; "
                                        f"limit {self.max_download_bytes})"
                                    ),
                                    "media": candidate,
                                }
                            ),
                        )
                    ]
                data = await attachment.read(use_cached=True)
            else:
                read_url = candidate.get("read_url")
                data, response_content_type = await self._download_embed(read_url)
                content_type = content_type or response_content_type

            filename = candidate.get("filename")
            kind = self._classify_media(content_type, filename)
            metadata = dict(candidate)
            metadata.update(
                {
                    "success": True,
                    "detected_kind": kind,
                    "downloaded_bytes": len(data),
                }
            )
            result: list = [
                TextContent(type="text", text=json.dumps(metadata, ensure_ascii=False))
            ]

            normalized_mime = (content_type or "").split(";", 1)[0].strip().lower()
            if (
                kind == "image"
                and normalized_mime in _DIRECT_IMAGE_MIME_TYPES
                and len(data) <= self.max_direct_image_bytes
            ):
                result.append(
                    ImageContent(
                        type="image",
                        data=base64.b64encode(data).decode("ascii"),
                        mime_type=normalized_mime,
                    )
                )
                return result

            if kind in {"image", "animated_image", "video"}:
                suffix = Path(filename or "").suffix.lower()
                result.extend(await self._frame_content(data, suffix, max_frames if kind != "image" else 1))
                return result

            result[0] = TextContent(
                type="text",
                text=json.dumps(
                    {
                        **metadata,
                        "success": False,
                        "message": "Media type is not a supported image, GIF, or video",
                    },
                    ensure_ascii=False,
                ),
            )
            return result

        return await self.admin_service._run(op)


discord_media_service = DiscordMediaService()
