"""`bound_tool_artifact` — the per-tool artifact policy at the MCP seam."""

import pytest
from langchain_core.messages import ToolMessage
from langchain_core.tools import Tool

from app.mcp.client.tools import bound_tool_artifact


APP = {"mcp_app_resource_uri": "ui://app/main", "mcp_server_id": "s1"}
DRIVE_ARTIFACT = {
    "structured_content": {"content": "iVBOR" * 100_000, "mimeType": "image/png"}
}


def _tool(result) -> Tool:
    async def coroutine(**kwargs):
        return result

    return Tool(name="t", description="", func=lambda **kw: None, coroutine=coroutine)


@pytest.mark.asyncio
async def test_a_plain_tool_loses_its_structured_content():
    tool = _tool(("the text the model sees", DRIVE_ARTIFACT))
    bound_tool_artifact(tool, None)
    content, artifact = await tool.coroutine()
    assert content == "the text the model sees"
    assert artifact is None


@pytest.mark.asyncio
async def test_a_plain_tool_keeps_other_artifact_keys():
    tool = _tool(("ok", {"structuredContent": {"big": 1}, "meta": {"page": 2}}))
    bound_tool_artifact(tool, None)
    _, artifact = await tool.coroutine()
    assert artifact == {"meta": {"page": 2}}


@pytest.mark.asyncio
async def test_an_app_tool_keeps_structured_content_and_is_stamped():
    tool = _tool(("ok", {"structured_content": {"rows": [1, 2]}}))
    bound_tool_artifact(tool, APP)
    _, artifact = await tool.coroutine()
    assert artifact == {"structured_content": {"rows": [1, 2]}, **APP}


@pytest.mark.asyncio
async def test_an_app_tool_without_an_artifact_still_gets_stamped():
    tool = _tool(("ok", None))
    bound_tool_artifact(tool, APP)
    _, artifact = await tool.coroutine()
    assert artifact == APP


@pytest.mark.asyncio
async def test_a_tool_message_result_is_rewritten_in_place():
    msg = ToolMessage(content="ok", tool_call_id="c1", artifact=dict(DRIVE_ARTIFACT))
    tool = _tool(msg)
    bound_tool_artifact(tool, None)
    result = await tool.coroutine()
    assert result is msg and result.artifact is None


@pytest.mark.asyncio
async def test_non_dict_artifacts_and_other_results_pass_through():
    tool = _tool(("ok", ["a", "list"]))
    bound_tool_artifact(tool, None)
    assert await tool.coroutine() == ("ok", ["a", "list"])
    plain = _tool("just a string")
    bound_tool_artifact(plain, None)
    assert await plain.coroutine() == "just a string"


@pytest.mark.asyncio
async def test_incomplete_ui_metadata_means_not_an_app_tool():
    tool = _tool(("ok", DRIVE_ARTIFACT))
    bound_tool_artifact(tool, {"mcp_app_resource_uri": "ui://x"})  # no server id
    _, artifact = await tool.coroutine()
    assert artifact is None
