from unittest.mock import AsyncMock
import json

import pytest
from mcp import Client
from mcp.types import TextContent
from pydantic import TypeAdapter, ValidationError

from mcp_server import mcp_server, discord_admin_service
from utils.discord_ids import Snowflake, stringify_discord_ids


IDS = ("736926591246008350", "1315614061261619210")


@pytest.mark.parametrize("value", IDS)
def test_snowflake_strings_are_parsed_without_rounding(value):
    assert TypeAdapter(Snowflake).validate_python(value) == int(value)


@pytest.mark.parametrize("value", [True, 1.5, float(IDS[1]), "0", "-1", " 123", "1e18", "١٢٣", str(2**64)])
def test_invalid_or_float_ids_are_rejected(value):
    with pytest.raises(ValidationError):
        TypeAdapter(Snowflake).validate_python(value)


def test_nested_id_output_keeps_non_identity_numbers_numeric():
    result = stringify_discord_ids({"id": int(IDS[1]), "guild_ids": [int(IDS[0])],
        "user": {"id": int(IDS[0])}, "category_id": None, "count": 48,
        "position": 3, "allowed": True})
    assert result == {"id": IDS[1], "guild_ids": [IDS[0]], "user": {"id": IDS[0]},
                      "category_id": None, "count": 48, "position": 3, "allowed": True}
    text = TextContent(type="text", text=json.dumps({"message_id": int(IDS[1])}))
    assert json.loads(stringify_discord_ids(text).text) == {"message_id": IDS[1]}


@pytest.mark.asyncio
async def test_every_mcp_identity_parameter_advertises_string_schema():
    async with Client(mcp_server) as client:
        tools = (await client.list_tools()).tools
    for tool in tools:
        for name, prop in tool.input_schema.get("properties", {}).items():
            if not name.endswith(("_id", "_ids")):
                continue
            options = prop.get("anyOf", [prop])
            actual = next(option for option in options if option.get("type") != "null")
            if name.endswith("_ids"):
                actual = actual["items"]
            assert actual["type"] == "string", (tool.name, name, prop)


@pytest.mark.asyncio
async def test_real_mcp_list_lookup_roundtrip_preserves_exact_snowflakes(monkeypatch):
    monkeypatch.setattr(discord_admin_service, "list_guilds", AsyncMock(return_value={
        "guilds": [{"id": int(IDS[1]), "name": "NsTut"}]}))
    channels = AsyncMock(return_value={"channels": [{"id": int(IDS[0]), "name": "endless"}], "count": 1})
    monkeypatch.setattr(discord_admin_service, "list_channels", channels)
    async with Client(mcp_server) as client:
        servers = await client.call_tool("discord_list_servers", {})
        guild_id = json.loads(servers.content[0].text)["guilds"][0]["id"]
        result = await client.call_tool("discord_list_channels", {"guild_id": guild_id})
    assert guild_id == IDS[1]
    channels.assert_awaited_once_with(int(IDS[1]), include_threads=True)
    assert json.loads(result.content[0].text) == {"channels": [{"id": IDS[0], "name": "endless"}], "count": 1}
