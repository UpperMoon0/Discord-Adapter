"""MCP tools for inspecting and mutating the runtime Discord access policy."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field


POLICY_TOOL_NAMES = {
    "discord_get_access_policy",
    "discord_reload_access_policy",
    "discord_policy_allow_guild",
    "discord_policy_remove_guild",
}


def register_policy_tools(server, policy_service, read_only, write, destructive) -> set[str]:
    """Register privileged Redis-backed access-policy tools."""

    @server.tool(
        title="Get Discord access policy",
        description="Read the active Redis-backed Discord guild access policy, store readiness, revision, and policy-write capability state.",
        annotations=read_only,
    )
    async def discord_get_access_policy() -> dict:
        return {"success": True, "policy": policy_service.status()}

    @server.tool(
        title="Reload Discord access policy",
        description="Reload the authoritative Discord guild access policy from Redis and atomically replace the in-memory snapshot on success.",
        annotations=read_only,
    )
    async def discord_reload_access_policy() -> dict:
        return await policy_service.reload()

    @server.tool(
        title="Allow Discord guild in access policy",
        description="Privileged policy mutation: allow one Discord guild. Requires deployment-level MCP_POLICY_WRITES_ENABLED=true; ordinary Discord admin access is insufficient.",
        annotations=write,
    )
    async def discord_policy_allow_guild(
        guild_id: Annotated[int, Field(gt=0, description="Discord guild/server ID to allow")],
    ) -> dict:
        return await policy_service.allow_guild(
            guild_id,
            caller_context={"surface": "mcp", "tool": "discord_policy_allow_guild"},
        )

    @server.tool(
        title="Remove Discord guild from access policy",
        description="Privileged policy mutation: remove one Discord guild from the allowlist. Requires deployment-level MCP_POLICY_WRITES_ENABLED=true.",
        annotations=destructive,
    )
    async def discord_policy_remove_guild(
        guild_id: Annotated[int, Field(gt=0, description="Discord guild/server ID to remove")],
    ) -> dict:
        return await policy_service.remove_guild(
            guild_id,
            caller_context={"surface": "mcp", "tool": "discord_policy_remove_guild"},
        )

    return POLICY_TOOL_NAMES.copy()
