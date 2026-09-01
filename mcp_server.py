"""MCP tool surface for guild-scoped Discord administration."""

from __future__ import annotations

import os
from typing import Annotated

from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import Field
from starlette.responses import JSONResponse

from services.discord_admin_service import discord_admin_service


READ_ONLY = ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=True)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=True)
DESTRUCTIVE = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=False, open_world_hint=True)

mcp_server = MCPServer(
    "Lily Discord Admin",
    instructions=(
        "Administer only Discord guilds returned by discord_list_servers. "
        "Always resolve the intended guild/member/channel before a write. "
        "Use a separate tool call for each guild when applying an action to multiple servers."
    ),
)


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
    annotations=READ_ONLY,
)
async def discord_list_servers() -> dict:
    """List Discord servers explicitly enabled for MCP administration and Lily's moderation capabilities."""
    return await discord_admin_service.list_guilds()


@mcp_server.tool(title="List Discord channels", annotations=READ_ONLY)
async def discord_list_channels(
    guild_id: Annotated[int, Field(description="Discord guild/server ID from discord_list_servers")],
) -> dict:
    """List channels in one allowed Discord server."""
    return await discord_admin_service.list_channels(guild_id)


@mcp_server.tool(title="Find Discord members", annotations=READ_ONLY)
async def discord_find_members(
    guild_id: Annotated[int, Field(description="Discord guild/server ID")],
    query: Annotated[str, Field(min_length=1, description="Username, display name, global name, or exact user ID")],
    limit: Annotated[int, Field(ge=1, le=50)] = 20,
) -> dict:
    """Search members in one allowed Discord server."""
    return await discord_admin_service.find_members(guild_id, query, limit)


@mcp_server.tool(title="Get Discord member", annotations=READ_ONLY)
async def discord_get_member(
    guild_id: Annotated[int, Field(description="Discord guild/server ID")],
    user_id: Annotated[int, Field(description="Discord user ID")],
) -> dict:
    """Get one member and their roles/timeout state."""
    return await discord_admin_service.get_member(guild_id, user_id)


@mcp_server.tool(title="Read Discord messages", annotations=READ_ONLY)
async def discord_read_messages(
    guild_id: Annotated[int, Field(description="Discord guild/server ID")],
    channel_id: Annotated[int, Field(description="Discord text channel ID")],
    limit: Annotated[int, Field(ge=1, le=100)] = 25,
) -> dict:
    """Read recent messages from one text channel."""
    return await discord_admin_service.read_messages(guild_id, channel_id, limit)


@mcp_server.tool(title="List Discord roles", annotations=READ_ONLY)
async def discord_list_roles(
    guild_id: Annotated[int, Field(description="Discord guild/server ID")],
) -> dict:
    """List roles in one allowed Discord server."""
    return await discord_admin_service.list_roles(guild_id)


@mcp_server.tool(title="Read Discord audit log", annotations=READ_ONLY)
async def discord_get_audit_log(
    guild_id: Annotated[int, Field(description="Discord guild/server ID")],
    limit: Annotated[int, Field(ge=1, le=100)] = 25,
) -> dict:
    """Read recent server audit-log entries when Lily has View Audit Log."""
    return await discord_admin_service.get_audit_log(guild_id, limit)


@mcp_server.tool(title="Send Discord message", annotations=WRITE)
async def discord_send_message(
    guild_id: Annotated[int, Field(description="Discord guild/server ID")],
    channel_id: Annotated[int, Field(description="Discord text channel ID")],
    content: Annotated[str, Field(min_length=1, max_length=2000)],
) -> dict:
    """Send a message as Lily. Mentions are disabled to prevent accidental mass pings."""
    return await discord_admin_service.send_message(guild_id, channel_id, content)


@mcp_server.tool(title="Delete Discord message", annotations=DESTRUCTIVE)
async def discord_delete_message(
    guild_id: Annotated[int, Field(description="Discord guild/server ID")],
    channel_id: Annotated[int, Field(description="Discord text channel ID")],
    message_id: Annotated[int, Field(description="Discord message ID")],
    reason: Annotated[str, Field(max_length=512)] = "MCP admin action",
) -> dict:
    """Delete one Discord message."""
    return await discord_admin_service.delete_message(guild_id, channel_id, message_id, reason)


@mcp_server.tool(title="Timeout Discord member", annotations=DESTRUCTIVE)
async def discord_timeout_member(
    guild_id: Annotated[int, Field(description="Discord guild/server ID")],
    user_id: Annotated[int, Field(description="Discord user ID")],
    duration_seconds: Annotated[int, Field(ge=1, le=2_419_200, description="Timeout duration, maximum 28 days")],
    reason: Annotated[str, Field(max_length=512)] = "MCP admin action",
) -> dict:
    """Timeout a member in one Discord server."""
    return await discord_admin_service.timeout_member(guild_id, user_id, duration_seconds, reason)


@mcp_server.tool(title="Clear Discord timeout", annotations=WRITE)
async def discord_clear_timeout(
    guild_id: Annotated[int, Field(description="Discord guild/server ID")],
    user_id: Annotated[int, Field(description="Discord user ID")],
    reason: Annotated[str, Field(max_length=512)] = "MCP admin action",
) -> dict:
    """Remove a member timeout."""
    return await discord_admin_service.clear_timeout(guild_id, user_id, reason)


@mcp_server.tool(title="Kick Discord member", annotations=DESTRUCTIVE)
async def discord_kick_member(
    guild_id: Annotated[int, Field(description="Discord guild/server ID")],
    user_id: Annotated[int, Field(description="Discord user ID")],
    reason: Annotated[str, Field(max_length=512)] = "MCP admin action",
) -> dict:
    """Kick a member from one Discord server."""
    return await discord_admin_service.kick_member(guild_id, user_id, reason)


@mcp_server.tool(title="Ban Discord member", annotations=DESTRUCTIVE)
async def discord_ban_member(
    guild_id: Annotated[int, Field(description="Discord guild/server ID")],
    user_id: Annotated[int, Field(description="Discord user ID")],
    reason: Annotated[str, Field(max_length=512)] = "MCP admin action",
    delete_message_seconds: Annotated[int, Field(ge=0, le=604_800)] = 0,
) -> dict:
    """Ban a user from one Discord server."""
    return await discord_admin_service.ban_member(guild_id, user_id, reason, delete_message_seconds)


@mcp_server.tool(title="Unban Discord member", annotations=WRITE)
async def discord_unban_member(
    guild_id: Annotated[int, Field(description="Discord guild/server ID")],
    user_id: Annotated[int, Field(description="Discord user ID")],
    reason: Annotated[str, Field(max_length=512)] = "MCP admin action",
) -> dict:
    """Unban a user from one Discord server."""
    return await discord_admin_service.unban_member(guild_id, user_id, reason)


@mcp_server.tool(title="Add Discord role", annotations=WRITE)
async def discord_add_role(
    guild_id: Annotated[int, Field(description="Discord guild/server ID")],
    user_id: Annotated[int, Field(description="Discord user ID")],
    role_id: Annotated[int, Field(description="Discord role ID")],
    reason: Annotated[str, Field(max_length=512)] = "MCP admin action",
) -> dict:
    """Assign one existing role to a member."""
    return await discord_admin_service.add_role(guild_id, user_id, role_id, reason)


@mcp_server.tool(title="Remove Discord role", annotations=DESTRUCTIVE)
async def discord_remove_role(
    guild_id: Annotated[int, Field(description="Discord guild/server ID")],
    user_id: Annotated[int, Field(description="Discord user ID")],
    role_id: Annotated[int, Field(description="Discord role ID")],
    reason: Annotated[str, Field(max_length=512)] = "MCP admin action",
) -> dict:
    """Remove one role from a member."""
    return await discord_admin_service.remove_role(guild_id, user_id, role_id, reason)


@mcp_server.tool(title="Create Discord text channel", annotations=WRITE)
async def discord_create_text_channel(
    guild_id: Annotated[int, Field(description="Discord guild/server ID")],
    name: Annotated[str, Field(min_length=1, max_length=100)],
    topic: Annotated[str | None, Field(max_length=1024)] = None,
    category_id: Annotated[int | None, Field(description="Optional Discord category ID")] = None,
    reason: Annotated[str, Field(max_length=512)] = "MCP admin action",
) -> dict:
    """Create a text channel."""
    return await discord_admin_service.create_text_channel(guild_id, name, topic, category_id, reason)


@mcp_server.tool(title="Update Discord text channel", annotations=WRITE)
async def discord_update_text_channel(
    guild_id: Annotated[int, Field(description="Discord guild/server ID")],
    channel_id: Annotated[int, Field(description="Discord text channel ID")],
    name: Annotated[str | None, Field(min_length=1, max_length=100)] = None,
    topic: Annotated[str | None, Field(max_length=1024)] = None,
    slowmode_delay: Annotated[int | None, Field(ge=0, le=21_600)] = None,
    reason: Annotated[str, Field(max_length=512)] = "MCP admin action",
) -> dict:
    """Change a text channel's basic settings."""
    return await discord_admin_service.update_text_channel(
        guild_id, channel_id, name, topic, slowmode_delay, reason
    )


@mcp_server.tool(title="Delete Discord channel", annotations=DESTRUCTIVE)
async def discord_delete_channel(
    guild_id: Annotated[int, Field(description="Discord guild/server ID")],
    channel_id: Annotated[int, Field(description="Discord channel ID")],
    reason: Annotated[str, Field(max_length=512)] = "MCP admin action",
) -> dict:
    """Delete a Discord channel."""
    return await discord_admin_service.delete_channel(guild_id, channel_id, reason)


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
