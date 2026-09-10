"""`serialize_message_preview` — the size-bounded projection a thread snapshot
(`GET /state`, `/history`, `GET /threads/{id}`) ships instead of whole tool
results. The whole result is served by `GET /threads/{id}/messages/{id}`."""

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agents.protocol.messages import (
    TOOL_PREVIEW_CHARS,
    serialize_message,
    serialize_message_preview,
)


def _tool(content, artifact=None, **kw) -> ToolMessage:
    return ToolMessage(
        content=content, tool_call_id="call_1", id="m1", artifact=artifact, **kw
    )


def test_a_long_tool_result_is_cut_and_marked():
    body = "x" * (TOOL_PREVIEW_CHARS + 500)
    d = serialize_message_preview(_tool(body))
    assert d["content"] == "x" * TOOL_PREVIEW_CHARS
    assert d["additional_kwargs"]["truncated"] == {"chars": TOOL_PREVIEW_CHARS + 500}


def test_a_short_tool_result_is_untouched():
    msg = _tool("short", additional_kwargs={"keep": 1})
    assert serialize_message_preview(msg) == serialize_message(msg)


def test_block_content_is_previewed_as_text():
    """MCP tools return `[{"type": "text", "text": …}]`; the preview is the
    text itself (the client renders a string preview verbatim)."""
    big = "y" * (TOOL_PREVIEW_CHARS * 2)
    d = serialize_message_preview(_tool([{"type": "text", "text": big}]))
    assert d["content"] == "y" * TOOL_PREVIEW_CHARS
    assert d["additional_kwargs"]["truncated"]["chars"] == len(big)


def test_the_limit_is_a_parameter():
    d = serialize_message_preview(_tool("abcdef"), limit=3)
    assert d["content"] == "abc"
    assert d["additional_kwargs"]["truncated"] == {"chars": 6}


def test_a_copy_artifact_is_dropped_but_an_app_artifact_is_kept():
    copy = serialize_message_preview(
        _tool("ok", artifact={"structured_content": {"a": 1}})
    )
    assert "artifact" not in copy
    app_artifact = {
        "mcp_app_resource_uri": "ui://app/main",
        "mcp_server_id": "s1",
        "structuredContent": {"rows": [1, 2, 3]},
    }
    app = serialize_message_preview(_tool("ok", artifact=app_artifact))
    assert app["artifact"] == app_artifact


def test_a_non_dict_artifact_is_dropped_too():
    d = serialize_message_preview(_tool("ok", artifact=["raw", "blocks"]))
    assert "artifact" not in d


def test_non_tool_messages_are_serialized_whole():
    long = "z" * (TOOL_PREVIEW_CHARS * 3)
    for msg in (HumanMessage(content=long, id="h"), AIMessage(content=long, id="a")):
        assert serialize_message_preview(msg) == serialize_message(msg)
