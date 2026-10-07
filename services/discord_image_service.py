"""Safe Discord image uploads from authenticated MCP requests.

The caller supplies image bytes as bounded base64; the server never follows
caller-provided URLs or reads arbitrary host filesystem paths.
"""

from __future__ import annotations

import base64
import binascii
import io
import os
import re

import discord

from services.discord_admin_service import DiscordAdminService, discord_admin_service

_SAFE_FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}\.(?:png|jpg|jpeg|webp|gif)$", re.I)
_DEFAULT_MAX_BYTES = 8 * 1024 * 1024


def _max_upload_bytes() -> int:
    try:
        value = int(os.getenv("DISCORD_IMAGE_MAX_UPLOAD_BYTES", str(_DEFAULT_MAX_BYTES)))
    except ValueError:
        return _DEFAULT_MAX_BYTES
    return max(1, min(value, _DEFAULT_MAX_BYTES))


def decode_image(image_base64: str, filename: str, max_bytes: int) -> bytes:
    """Validate size, base64, extension, and image signature before upload."""
    if not _SAFE_FILENAME.fullmatch(filename) or ".." in filename:
        raise ValueError("filename must be a safe .png, .jpg, .jpeg, .webp, or .gif basename")
    payload = image_base64.strip()
    if len(payload) > ((max_bytes + 2) // 3) * 4 + 4:
        raise ValueError(f"image exceeds the {max_bytes}-byte upload limit")
    try:
        raw = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("image_base64 is not valid base64 image data") from exc
    if not raw or len(raw) > max_bytes:
        raise ValueError(f"image must be 1 to {max_bytes} bytes")

    ext = filename.rsplit(".", 1)[-1].lower()
    recognized = (
        (ext == "png" and raw.startswith(b"\x89PNG\r\n\x1a\n"))
        or (ext in {"jpg", "jpeg"} and raw.startswith(b"\xff\xd8\xff"))
        or (ext == "webp" and raw.startswith(b"RIFF") and raw[8:12] == b"WEBP")
        or (ext == "gif" and raw[:6] in {b"GIF87a", b"GIF89a"})
    )
    if not recognized:
        raise ValueError("image bytes do not match the filename's image format")
    return raw


class DiscordImageService:
    def __init__(self, admin_service: DiscordAdminService = discord_admin_service):
        self.admin_service = admin_service
        self.max_upload_bytes = _max_upload_bytes()

    async def send_image(
        self,
        guild_id: int,
        channel_id: int,
        image_base64: str,
        filename: str = "image.png",
        caption: str = "",
        reply_to_message_id: int | None = None,
    ) -> dict:
        if len(caption) > 2000:
            return {"success": False, "message": "caption exceeds 2000 characters"}
        if reply_to_message_id is not None and reply_to_message_id <= 0:
            return {"success": False, "message": "reply_to_message_id must be a positive Discord ID"}
        try:
            image = decode_image(image_base64, filename, self.max_upload_bytes)
        except ValueError as exc:
            return {"success": False, "message": str(exc)}

        async def op() -> dict:
            guild, error = self.admin_service._guild(guild_id)
            if error:
                return error
            channel = self.admin_service._channel(guild, channel_id)
            if not isinstance(channel, (discord.TextChannel, discord.Thread)):
                return {"success": False, "message": f"Channel {channel_id} is not a text channel"}
            reference = None
            if reply_to_message_id is not None:
                reference = await channel.fetch_message(reply_to_message_id)

            # The image is an actual attachment, not a text/link embed. No
            # mentions are allowed even if the caption contains @everyone.
            upload = discord.File(io.BytesIO(image), filename=filename)
            try:
                message = await channel.send(
                    content=caption or None,
                    file=upload,
                    allowed_mentions=discord.AllowedMentions.none(),
                    reference=reference,
                    mention_author=False,
                )
            finally:
                upload.close()

            return {
                "success": True,
                "guild_id": guild.id,
                "channel_id": channel.id,
                "message_id": message.id,
                "jump_url": message.jump_url,
                "filename": filename,
                "size_bytes": len(image),
                "reply_to_message_id": reply_to_message_id,
            }

        return await self.admin_service._run(op)


discord_image_service = DiscordImageService()
