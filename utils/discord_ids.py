"""Lossless Discord snowflakes at the JSON/MCP boundary."""

import json
from typing import Annotated

from mcp.types import TextContent
from pydantic import BeforeValidator, WithJsonSchema


def parse_snowflake(value):
    # Never accept floats: a JavaScript number may already have lost precision.
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError("Discord IDs must be decimal strings")
    if isinstance(value, str) and (not value.isascii() or not value.isdigit()):
        raise ValueError("Discord IDs must be decimal strings")
    result = int(value)
    if not 0 < result < 2**64:
        raise ValueError("Discord IDs must be positive unsigned 64-bit snowflakes")
    return result


Snowflake = Annotated[
    int,
    BeforeValidator(parse_snowflake),
    WithJsonSchema({"type": "string", "pattern": "^[1-9][0-9]{0,19}$"}),
]


def stringify_discord_ids(value, key=""):
    """Keep service arithmetic numeric; serialize identity fields as strings."""
    if isinstance(value, TextContent):
        try:
            payload = json.loads(value.text)
        except (ValueError, TypeError):
            return value
        return value.model_copy(update={"text": json.dumps(stringify_discord_ids(payload))})
    if isinstance(value, dict):
        return {name: stringify_discord_ids(item, name) for name, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [stringify_discord_ids(item, key) for item in value]
    if isinstance(value, int) and not isinstance(value, bool) and (
        key == "id" or key.endswith("_id") or key.endswith("_ids")
    ):
        return str(value)
    return value
