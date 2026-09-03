"""MCP tools for inspecting visual media attached to Discord messages."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from mcp_media_app import MEDIA_UI_RESOURCE_URI


MEDIA_TOOL_NAMES = {
    "discord_list_message_media",
    "discord_read_message_media",
}


def register_media_tools(server, service, read_only) -> set[str]:
    """Register read-only tools that let MCP clients actually inspect Discord media."""

    @server.tool(
        title="List Discord message media",
        description=(
            "List images, GIFs, and videos attached to or embedded in one Discord message. "
            "Use the returned media_index with discord_read_message_media to inspect the visual content."
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
            "Static images are returned directly when practical; GIFs and videos are sampled into representative frames."
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
            Field(ge=0, le=50, description="Zero-based media_index from discord_list_message_media"),
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

    return set(MEDIA_TOOL_NAMES)
