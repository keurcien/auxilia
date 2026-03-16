import pytest
from langchain_core.messages import ToolMessage

from app.mcp.client.tools import inject_ui_metadata_into_tool


class DummyTool:
    def __init__(self, result):
        async def _coroutine(*_args, **_kwargs):
            return result

        self.coroutine = _coroutine


@pytest.mark.asyncio
async def test_inject_ui_metadata_into_tool_tuple_result_without_artifact_dict():
    tool = DummyTool(("ok", None))

    inject_ui_metadata_into_tool(
        tool,
        {
            "mcp_app_resource_uri": "ui://chart/pie",
            "mcp_server_id": "server-1",
        },
    )

    _, artifact = await tool.coroutine()

    assert artifact["mcp_app_resource_uri"] == "ui://chart/pie"
    assert artifact["mcp_server_id"] == "server-1"


@pytest.mark.asyncio
async def test_inject_ui_metadata_into_tool_message_without_artifact_dict():
    tool = DummyTool(ToolMessage(content="ok", tool_call_id="call-1"))

    inject_ui_metadata_into_tool(
        tool,
        {
            "mcp_app_resource_uri": "ui://chart/pie",
            "mcp_server_id": "server-1",
        },
    )

    result = await tool.coroutine()

    assert isinstance(result, ToolMessage)
    assert result.artifact["mcp_app_resource_uri"] == "ui://chart/pie"
    assert result.artifact["mcp_server_id"] == "server-1"
