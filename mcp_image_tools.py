"""Write-only MCP tool for posting a real Discord image attachment."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from services.discord_image_service import discord_image_service
from utils.discord_ids import Snowflake

IMAGE_TOOL_NAMES = {"discord_send_image"}


def register_image_tools(server, service=discord_image_service, write=None):
    @server.tool(
        title="Send Discord image attachment",
        description=(
            "Upload one PNG, JPEG, WebP, or GIF image as a real Discord attachment to an "
            "allowed guild channel. Supply the actual image bytes as base64, not a local "
            "path or a link. Captions are optional; all mentions, including replies, are "
            "suppressed. Maximum decoded image size defaults to 8 MiB. "
            "Never use this tool for a dry run: it posts immediately."
        ),
        annotations=write,
    )
    async def discord_send_image(
        guild_id: Annotated[Snowflake, Field(description="Discord guild/server ID")],
        channel_id: Annotated[Snowflake, Field(description="Discord text channel ID")],
        image_base64: Annotated[str, Field(min_length=8, max_length=11_184_816, description="Base64-encoded image bytes (no data-URL prefix, max 8 MiB decoded)")],
        filename: Annotated[str, Field(max_length=100, description="Safe image filename and extension")] = "image.png",
        caption: Annotated[str, Field(max_length=2000, description="Optional plain-text caption; no pings")] = "",
        reply_to_message_id: Annotated[
            Snowflake | None, Field(gt=0, description="Optional message ID to reply to without pinging the author")
        ] = None,
    ) -> dict:
        return await service.send_image(
            guild_id,
            channel_id,
            image_base64,
            filename=filename,
            caption=caption,
            reply_to_message_id=reply_to_message_id,
        )

    return IMAGE_TOOL_NAMES
