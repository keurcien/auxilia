"""Per-tool policy for MCP results, at the seam where they become ToolMessages.

langchain-mcp-adapters wraps every MCP tool with
``response_format="content_and_artifact"``: the text/image blocks become the
model-visible ``content`` and the server's ``structuredContent`` becomes
``ToolMessage.artifact`` — whole, uncapped. The model never sees the artifact,
but the checkpointer, the run event log, Langfuse and the thread snapshot all
serialise it, and nothing that manages context size (deepagents' eviction,
summarisation) looks at it, because it costs no tokens. A Google Drive
``download_file_content`` puts the file's base64 there: 8 MB per call that rode
along in every checkpoint of the thread — 96% of one production thread's state.

Two policies, chosen per tool when the toolset is built:

- **MCP-app tools** (a ``resourceUri`` on the tool definition): the widget
  iframe consumes ``structuredContent``, so the artifact is kept whole and
  stamped with the app resource URI and server id — how the client recognises
  an app result on hydration, since LangGraph persists the ToolMessage as is.
- **Every other tool**: ``structured_content`` is dropped. No client code reads
  it and the model never had it.
"""

from langchain_core.messages import ToolMessage
from langchain_core.tools import Tool


_STRUCTURED_CONTENT_KEYS = ("structured_content", "structuredContent")


def bound_tool_artifact(tool: Tool, ui_metadata: dict | None) -> None:
    """Wrap a tool's coroutine in place so every result's artifact follows the
    policy above: stamped and kept whole for an app tool (`ui_metadata` carries
    `mcp_app_resource_uri` + `mcp_server_id`), stripped of structured content
    for any other."""
    resource_uri = (ui_metadata or {}).get("mcp_app_resource_uri")
    server_id = (ui_metadata or {}).get("mcp_server_id")
    is_app_tool = bool(resource_uri and server_id)

    original_coroutine = tool.coroutine
    if original_coroutine is None:
        return

    def rewrite(artifact):
        if is_app_tool:
            stamped = dict(artifact) if isinstance(artifact, dict) else {}
            stamped["mcp_app_resource_uri"] = resource_uri
            stamped["mcp_server_id"] = server_id
            return stamped
        if isinstance(artifact, dict):
            trimmed = {
                k: v for k, v in artifact.items() if k not in _STRUCTURED_CONTENT_KEYS
            }
            return trimmed or None
        return artifact

    async def bounded_coroutine(*args, **kwargs):
        result = await original_coroutine(*args, **kwargs)
        if isinstance(result, tuple) and len(result) == 2:
            content, artifact = result
            return content, rewrite(artifact)
        if isinstance(result, ToolMessage):
            result.artifact = rewrite(result.artifact)
        return result

    tool.coroutine = bounded_coroutine
