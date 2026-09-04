import pytest
from mcp import Client

from mcp_compact_tools import (
    COMPACT_TOOL_NAMES,
    LEGACY_BASE_TOOL_NAMES,
    LEGACY_EXTENDED_TOOL_NAMES,
    LEGACY_POLICY_TOOL_NAMES,
)
from mcp_extended_tools import EXTENDED_TOOL_NAMES
from mcp_media_tools import MEDIA_TOOL_NAMES
from mcp_policy_tools import POLICY_TOOL_NAMES
from mcp_server import mcp_server


BASE_TOOL_NAMES = {
    "discord_list_servers",
    "discord_list_channels",
    "discord_list_members",
    "discord_find_members",
    "discord_get_member",
    "discord_read_messages",
    "discord_list_roles",
    "discord_get_audit_log",
    "discord_send_message",
    "discord_delete_message",
    "discord_timeout_member",
    "discord_clear_timeout",
    "discord_kick_member",
    "discord_ban_member",
    "discord_unban_member",
    "discord_add_role",
    "discord_remove_role",
    "discord_create_text_channel",
    "discord_update_text_channel",
    "discord_delete_channel",
}


@pytest.mark.asyncio
async def test_runtime_mcp_tool_surface_is_compact_complete_and_described():
    """Verify the SDK advertises only the intended compact semantic surface."""
    async with Client(mcp_server) as client:
        result = await client.list_tools()

    tools = {tool.name: tool for tool in result.tools}
    expected = (
        (BASE_TOOL_NAMES - LEGACY_BASE_TOOL_NAMES)
        | (EXTENDED_TOOL_NAMES - LEGACY_EXTENDED_TOOL_NAMES)
        | (POLICY_TOOL_NAMES - LEGACY_POLICY_TOOL_NAMES)
        | COMPACT_TOOL_NAMES
        | MEDIA_TOOL_NAMES
    )

    assert set(tools) == expected
    assert len(tools) == 52
    assert all(tool.description and tool.description.strip() for tool in tools.values())


@pytest.mark.asyncio
async def test_send_message_tool_advertises_rich_message_arguments():
    async with Client(mcp_server) as client:
        result = await client.list_tools()
    tool = next(tool for tool in result.tools if tool.name == "discord_send_message")
    properties = tool.input_schema["properties"]
    assert {"mention_user_ids", "mention_role_ids", "reply_to_message_id", "quote_message_id"}.issubset(properties)


@pytest.mark.asyncio
async def test_direct_message_tools_expose_read_and_rich_send_contracts():
    async with Client(mcp_server) as client:
        result = await client.list_tools()
    tools = {tool.name: tool for tool in result.tools}

    read_properties = tools["discord_direct_messages"].input_schema["properties"]
    assert {"user_id", "limit"}.issubset(read_properties)

    send_properties = tools["discord_send_direct_message"].input_schema["properties"]
    assert {"user_id", "content", "reply_to_message_id", "quote_message_id"}.issubset(send_properties)


@pytest.mark.asyncio
async def test_consolidated_tools_expose_configuration_switches():
    async with Client(mcp_server) as client:
        result = await client.list_tools()
    tools = {tool.name: tool for tool in result.tools}

    assert {"mode", "query", "user_id"}.issubset(tools["discord_query_members"].input_schema["properties"])
    assert {"assigned"}.issubset(tools["discord_set_member_role"].input_schema["properties"])
    assert {"duration_seconds"}.issubset(tools["discord_set_member_timeout"].input_schema["properties"])
    assert {"pinned"}.issubset(tools["discord_set_message_pin"].input_schema["properties"])
    assert {"clear", "permissions"}.issubset(tools["discord_set_channel_permissions"].input_schema["properties"])
    assert {"reload"}.issubset(tools["discord_get_access_policy"].input_schema["properties"])
    assert {"allowed"}.issubset(tools["discord_set_guild_access"].input_schema["properties"])


def test_destructive_operations_are_annotated_for_mcp_clients():
    """High-impact operations must advertise destructive intent to MCP hosts."""
    manager = mcp_server._tool_manager
    tools = {tool.name: tool for tool in manager.list_tools()}

    destructive = {
        "discord_delete_message",
        "discord_set_message_pin",
        "discord_set_member_timeout",
        "discord_kick_member",
        "discord_ban_member",
        "discord_set_member_role",
        "discord_delete_channel",
        "discord_delete_role",
        "discord_set_channel_permissions",
        "discord_delete_webhook",
        "discord_delete_emoji",
        "discord_delete_sticker",
        "discord_delete_invite",
        "discord_delete_thread",
        "discord_purge_messages",
        "discord_set_guild_access",
    }

    for name in destructive:
        annotations = tools[name].annotations
        assert annotations is not None
        assert annotations.destructive_hint is True, name
