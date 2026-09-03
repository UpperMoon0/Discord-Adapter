import pytest
from mcp import Client
from mcp.server.apps import APP_MIME_TYPE, EXTENSION_ID

from mcp_media_app import MEDIA_UI_RESOURCE_URI, MEDIA_VIEWER_HTML
from mcp_server import mcp_server


@pytest.mark.asyncio
async def test_media_reader_is_bound_to_renderable_mcp_app_resource():
    async with Client(mcp_server) as client:
        tools_result = await client.list_tools()
        resources_result = await client.list_resources()

    media_tool = next(
        tool for tool in tools_result.tools if tool.name == "discord_read_message_media"
    )
    assert media_tool.meta is not None
    assert media_tool.meta["ui"]["resourceUri"] == MEDIA_UI_RESOURCE_URI

    resource = next(
        item for item in resources_result.resources if str(item.uri) == MEDIA_UI_RESOURCE_URI
    )
    assert resource.mime_type == APP_MIME_TYPE


def test_mcp_apps_extension_is_advertised():
    assert EXTENSION_ID in mcp_server._lowlevel_server.extensions


def test_media_viewer_uses_csp_safe_data_urls_for_image_content():
    assert "URL.createObjectURL" not in MEDIA_VIEWER_HTML
    assert "data:${mime};base64,${image.data}" in MEDIA_VIEWER_HTML
