"""MCP tool surface for guild-scoped Discord administration."""

from __future__ import annotations

import os
from typing import Annotated

from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import Field
from starlette.responses import JSONResponse

from mcp_extended_tools import register_extended_tools
from mcp_policy_tools import register_policy_tools
from services.access_policy_service import access_policy_service
from services.extended_discord_admin_service import discord_admin_service


READ_ONLY = ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=True)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=True)
DESTRUCTIVE = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=False, open_world_hint=True)

mcp_server = MCPServer(
    "Lily Discord Admin",
    instructions=(
        "Administer only Discord guilds returned by discord_list_servers. "
        "Always resolve the intended guild/member/channel/role before a write. "
        "Use a separate tool call for each guild when applying an action to multiple servers. "
        "Prefer the narrow semantic tool for the requested operation; never infer IDs from names when lookup tools are available."
    ),
)


class _DescribedToolServer:
    """Proxy that guarantees extended tools expose a model-readable description."""

    def __init__(self, server: MCPServer):
        self._server = server

    def tool(self, **metadata):
        metadata.setdefault("description", metadata.get("title") or "Discord administration tool")
        return self._server.tool(**metadata)


def _csv_env(name: str) -> list[str]:
    """Read a comma-separated environment setting, dropping blank entries."""
    return [value.strip() for value in os.getenv(name, "").split(",") if value.strip()]


def _transport_security() -> TransportSecuritySettings:
    """
    Configure MCP's DNS-rebinding protection for both local/tunnel and hosted use.

    The MCP SDK defaults to localhost-only Host validation. Lily's production
    deployment already provides DOMAIN_NAME, so derive the public adapter host
    from it unless MCP_ALLOWED_HOSTS is explicitly configured.
    """
    allowed_hosts = _csv_env("MCP_ALLOWED_HOSTS")
    if not allowed_hosts:
        allowed_hosts = [
            "localhost",
            "localhost:*",
            "127.0.0.1",
            "127.0.0.1:*",
            "[::1]",
            "[::1]:*",
        ]

        domain = os.getenv("DOMAIN_NAME", "").strip().strip(".")
        if domain:
            public_host = (
                domain
                if domain.startswith("lily-discord-adapter.")
                else f"lily-discord-adapter.{domain}"
            )
            allowed_hosts.extend([public_host, f"{public_host}:*"])

    return TransportSecuritySettings(
        allowed_hosts=allowed_hosts,
        allowed_origins=_csv_env("MCP_ALLOWED_ORIGINS"),
    )


@mcp_server.tool(
    title="List allowed Discord servers",
    description="List Discord servers explicitly enabled for MCP administration and the bot's moderation capabilities in each server.",
    annotations=READ_ONLY,
)
async def discord_list_servers() -> dict:
    return await discord_admin_service.list_guilds()


@mcp_server.tool(
    title="List Discord channels",
    description="List channels in one allowed Discord server so a target channel can be resolved before an action.",
    annotations=READ_ONLY,
)
async def discord_list_channels(
    guild_id: Annotated[int, Field(description="Discord guild/server ID from discord_list_servers")],
) -> dict:
    return await discord_admin_service.list_channels(guild_id)


@mcp_server.tool(
    title="Find Discord members",
    description="Search members in one allowed Discord server by username, display name, global name, or exact user ID.",
    annotations=READ_ONLY,
)
async def discord_find_members(
    guild_id: Annotated[int, Field(description="Discord guild/server ID")],
    query: Annotated[str, Field(min_length=1, description="Username, display name, global name, or exact user ID")],
    limit: Annotated[int, Field(ge=1, le=50)] = 20,
) -> dict:
    return await discord_admin_service.find_members(guild_id, query, limit)


@mcp_server.tool(
    title="Get Discord member",
    description="Get one Discord member including roles and current timeout state.",
    annotations=READ_ONLY,
)
async def discord_get_member(
    guild_id: Annotated[int, Field(description="Discord guild/server ID")],
    user_id: Annotated[int, Field(description="Discord user ID")],
) -> dict:
    return await discord_admin_service.get_member(guild_id, user_id)


@mcp_server.tool(
    title="Read Discord messages",
    description="Read recent messages from one text channel or thread, including jump URLs and reply/reference metadata.",
    annotations=READ_ONLY,
)
async def discord_read_messages(
    guild_id: Annotated[int, Field(description="Discord guild/server ID")],
    channel_id: Annotated[int, Field(description="Discord text channel ID")],
    limit: Annotated[int, Field(ge=1, le=100)] = 25,
) -> dict:
    return await discord_admin_service.read_messages(guild_id, channel_id, limit)


@mcp_server.tool(
    title="List Discord roles",
    description="List roles in one allowed Discord server so role IDs can be resolved safely before role operations.",
    annotations=READ_ONLY,
)
async def discord_list_roles(
    guild_id: Annotated[int, Field(description="Discord guild/server ID")],
) -> dict:
    return await discord_admin_service.list_roles(guild_id)


@mcp_server.tool(
    title="Read Discord audit log",
    description="Read recent Discord server audit-log entries when the bot has View Audit Log permission.",
    annotations=READ_ONLY,
)
async def discord_get_audit_log(
    guild_id: Annotated[int, Field(description="Discord guild/server ID")],
    limit: Annotated[int, Field(ge=1, le=100)] = 25,
) -> dict:
    return await discord_admin_service.get_audit_log(guild_id, limit)


@mcp_server.tool(
    title="Send Discord message",
    description=(
        "Send one Discord message, optionally pinging explicitly selected users/roles, replying to a message, "
        "or quoting a message. Mentions are suppressed by default; @everyone/@here are never enabled."
    ),
    annotations=WRITE,
)
async def discord_send_message(
    guild_id: Annotated[int, Field(description="Discord guild/server ID")],
    channel_id: Annotated[int, Field(description="Discord text channel ID")],
    content: Annotated[str, Field(min_length=1, max_length=2000)],
    mention_user_ids: Annotated[
        list[int] | None,
        Field(description="Discord user IDs to prepend and ping; only these user mentions are allowed"),
    ] = None,
    mention_role_ids: Annotated[
        list[int] | None,
        Field(description="Discord role IDs to prepend and ping; only these role mentions are allowed"),
    ] = None,
    reply_to_message_id: Annotated[
        int | None,
        Field(description="Optional message ID in this channel to reply to without automatically pinging its author"),
    ] = None,
    quote_message_id: Annotated[
        int | None,
        Field(description="Optional message ID in this channel whose author/content should be quoted above the new content"),
    ] = None,
) -> dict:
    return await discord_admin_service.send_message(
        guild_id,
        channel_id,
        content,
        mention_user_ids=mention_user_ids,
        mention_role_ids=mention_role_ids,
        reply_to_message_id=reply_to_message_id,
        quote_message_id=quote_message_id,
    )


@mcp_server.tool(
    title="Delete Discord message",
    description="Delete one specific Discord message from one allowed server.",
    annotations=DESTRUCTIVE,
)
async def discord_delete_message(
    guild_id: Annotated[int, Field(description="Discord guild/server ID")],
    channel_id: Annotated[int, Field(description="Discord text channel ID")],
    message_id: Annotated[int, Field(description="Discord message ID")],
    reason: Annotated[str, Field(max_length=512)] = "MCP admin action",
) -> dict:
    return await discord_admin_service.delete_message(guild_id, channel_id, message_id, reason)


@mcp_server.tool(
    title="Timeout Discord member",
    description="Timeout one Discord member for a bounded duration of up to 28 days.",
    annotations=DESTRUCTIVE,
)
async def discord_timeout_member(
    guild_id: Annotated[int, Field(description="Discord guild/server ID")],
    user_id: Annotated[int, Field(description="Discord user ID")],
    duration_seconds: Annotated[int, Field(ge=1, le=2_419_200, description="Timeout duration, maximum 28 days")],
    reason: Annotated[str, Field(max_length=512)] = "MCP admin action",
) -> dict:
    return await discord_admin_service.timeout_member(guild_id, user_id, duration_seconds, reason)


@mcp_server.tool(
    title="Clear Discord timeout",
    description="Remove the current Discord timeout from one member.",
    annotations=WRITE,
)
async def discord_clear_timeout(
    guild_id: Annotated[int, Field(description="Discord guild/server ID")],
    user_id: Annotated[int, Field(description="Discord user ID")],
    reason: Annotated[str, Field(max_length=512)] = "MCP admin action",
) -> dict:
    return await discord_admin_service.clear_timeout(guild_id, user_id, reason)


@mcp_server.tool(
    title="Kick Discord member",
    description="Kick one member from an allowed Discord server.",
    annotations=DESTRUCTIVE,
)
async def discord_kick_member(
    guild_id: Annotated[int, Field(description="Discord guild/server ID")],
    user_id: Annotated[int, Field(description="Discord user ID")],
    reason: Annotated[str, Field(max_length=512)] = "MCP admin action",
) -> dict:
    return await discord_admin_service.kick_member(guild_id, user_id, reason)


@mcp_server.tool(
    title="Ban Discord member",
    description="Ban one user from an allowed Discord server and optionally delete recent messages.",
    annotations=DESTRUCTIVE,
)
async def discord_ban_member(
    guild_id: Annotated[int, Field(description="Discord guild/server ID")],
    user_id: Annotated[int, Field(description="Discord user ID")],
    reason: Annotated[str, Field(max_length=512)] = "MCP admin action",
    delete_message_seconds: Annotated[int, Field(ge=0, le=604_800)] = 0,
) -> dict:
    return await discord_admin_service.ban_member(guild_id, user_id, reason, delete_message_seconds)


@mcp_server.tool(
    title="Unban Discord member",
    description="Remove a Discord ban for one user ID in an allowed server.",
    annotations=WRITE,
)
async def discord_unban_member(
    guild_id: Annotated[int, Field(description="Discord guild/server ID")],
    user_id: Annotated[int, Field(description="Discord user ID")],
    reason: Annotated[str, Field(max_length=512)] = "MCP admin action",
) -> dict:
    return await discord_admin_service.unban_member(guild_id, user_id, reason)


@mcp_server.tool(
    title="Add Discord role",
    description="Assign one existing Discord role to one member.",
    annotations=WRITE,
)
async def discord_add_role(
    guild_id: Annotated[int, Field(description="Discord guild/server ID")],
    user_id: Annotated[int, Field(description="Discord user ID")],
    role_id: Annotated[int, Field(description="Discord role ID")],
    reason: Annotated[str, Field(max_length=512)] = "MCP admin action",
) -> dict:
    return await discord_admin_service.add_role(guild_id, user_id, role_id, reason)


@mcp_server.tool(
    title="Remove Discord role",
    description="Remove one existing Discord role from one member.",
    annotations=DESTRUCTIVE,
)
async def discord_remove_role(
    guild_id: Annotated[int, Field(description="Discord guild/server ID")],
    user_id: Annotated[int, Field(description="Discord user ID")],
    role_id: Annotated[int, Field(description="Discord role ID")],
    reason: Annotated[str, Field(max_length=512)] = "MCP admin action",
) -> dict:
    return await discord_admin_service.remove_role(guild_id, user_id, role_id, reason)


@mcp_server.tool(
    title="Create Discord text channel",
    description="Create a text channel in one allowed Discord server, optionally under a category.",
    annotations=WRITE,
)
async def discord_create_text_channel(
    guild_id: Annotated[int, Field(description="Discord guild/server ID")],
    name: Annotated[str, Field(min_length=1, max_length=100)],
    topic: Annotated[str | None, Field(max_length=1024)] = None,
    category_id: Annotated[int | None, Field(description="Optional Discord category ID")] = None,
    reason: Annotated[str, Field(max_length=512)] = "MCP admin action",
) -> dict:
    return await discord_admin_service.create_text_channel(guild_id, name, topic, category_id, reason)


@mcp_server.tool(
    title="Update Discord text channel",
    description="Change a text channel's name, topic, or slowmode delay.",
    annotations=WRITE,
)
async def discord_update_text_channel(
    guild_id: Annotated[int, Field(description="Discord guild/server ID")],
    channel_id: Annotated[int, Field(description="Discord text channel ID")],
    name: Annotated[str | None, Field(min_length=1, max_length=100)] = None,
    topic: Annotated[str | None, Field(max_length=1024)] = None,
    slowmode_delay: Annotated[int | None, Field(ge=0, le=21_600)] = None,
    reason: Annotated[str, Field(max_length=512)] = "MCP admin action",
) -> dict:
    return await discord_admin_service.update_text_channel(guild_id, channel_id, name, topic, slowmode_delay, reason)


@mcp_server.tool(
    title="Delete Discord channel",
    description="Delete one Discord channel or thread in an allowed server.",
    annotations=DESTRUCTIVE,
)
async def discord_delete_channel(
    guild_id: Annotated[int, Field(description="Discord guild/server ID")],
    channel_id: Annotated[int, Field(description="Discord channel ID")],
    reason: Annotated[str, Field(max_length=512)] = "MCP admin action",
) -> dict:
    return await discord_admin_service.delete_channel(guild_id, channel_id, reason)


# Register the larger semantic admin surface separately so it stays testable without
# coupling tests to MCPServer's private registry implementation. The proxy guarantees
# every extended tool exposes at least its human-readable title as a description.
register_extended_tools(
    _DescribedToolServer(mcp_server),
    discord_admin_service,
    READ_ONLY,
    WRITE,
    DESTRUCTIVE,
)

register_policy_tools(
    mcp_server,
    access_policy_service,
    READ_ONLY,
    WRITE,
    DESTRUCTIVE,
)


@mcp_server.custom_route("/health", methods=["GET"])
async def mcp_health(_request):
    """MCP-only liveness endpoint."""
    return JSONResponse(
        {
            "status": "ok",
            "service": "lily-discord-mcp",
            "guild_policy": discord_admin_service.policy_status(),
            "bearer_auth_configured": bool(os.getenv("MCP_BEARER_TOKEN")),
        }
    )


def build_mcp_asgi_app():
    """Build the mountable Streamable HTTP ASGI app."""
    return mcp_server.streamable_http_app(
        json_response=True,
        streamable_http_path="/",
        transport_security=_transport_security(),
    )
