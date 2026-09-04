"""MCP tools for inspecting visual media attached to Discord messages."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from mcp_media_app import MEDIA_UI_RESOURCE_URI


MEDIA_TOOL_NAMES = {
    "discord_list_message_media",
    "discord_read_message_media",
}


def register_media_tools(server, service, read_only) -> None:
    """Register read-only tools that let MCP clients inspect Discord media."""

    @server.tool(
        title="List Discord message media",
        description=(
            "List images, GIFs, and videos attached to or embedded in one Discord message. "
            "Use this only when media metadata is needed or a non-default media_index must be chosen. "
            "For the first/default media item, call discord_read_message_media directly instead of listing first."
        ),
        annotations=read_only,
    )
    async def discord_list_message_media(
        guild_id: Annotated[int, Field(description="Discord guild/server ID")],
        channel_id: Annotated[int, Field(description="Discord text channel or thread ID")],
        message_id: Annotated[int, Field(description="Discord message ID")],
    ) -> dict:
        return await service.list_message_media(guild_id, channel_id, message_id)

    @server.tool(
        title="Read Discord message media",
        description=(
            "Return actual visual media from one Discord message as MCP image content. "
            "Call this tool directly for the first/default media item with media_index=0; listing first is unnecessary. "
            "Static images are returned directly when small enough; larger images are normalized, and GIFs/videos are sampled into representative frames."
        ),
        annotations=read_only,
        meta={"ui": {"resourceUri": MEDIA_UI_RESOURCE_URI}},
        structured_output=False,
    )
    async def discord_read_message_media(
        guild_id: Annotated[int, Field(description="Discord guild/server ID")],
        channel_id: Annotated[int, Field(description="Discord text channel or thread ID")],
        message_id: Annotated[int, Field(description="Discord message ID")],
        media_index: Annotated[
            int,
            Field(
                ge=0,
                le=50,
                description=(
                    "Zero-based media index; defaults to the first item. "
                    "Use discord_list_message_media only when selecting among multiple media items."
                ),
            ),
        ] = 0,
        max_frames: Annotated[
            int,
            Field(
                ge=1,
                le=6,
                description="Maximum representative frames for GIF/video inspection",
            ),
        ] = 4,
    ) -> list:
        return await service.read_message_media(
            guild_id,
            channel_id,
            message_id,
            media_index=media_index,
            max_frames=max_frames,
        )
