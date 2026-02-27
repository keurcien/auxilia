from langchain_core.messages import ToolMessage
from langchain_core.tools import Tool
from langchain_core.tools.base import ToolException


def inject_ui_metadata_into_tool(tool: Tool, ui_metadata: dict) -> None:
    """Wrap a tool's coroutine in-place to persist MCP app UI metadata in ToolMessage artifacts.

    When a tool with a UI widget executes, this injects mcp_app_resource_uri and
    mcp_server_id into the returned ToolMessage.artifact dict. Because LangGraph
    persists ToolMessage objects in its checkpoint, this data is available when
    loading thread history, allowing widgets to be re-rendered on page refresh.

    Must be called AFTER wrap_mcp_tool_errors so exceptions are already handled.
    """
    resource_uri = ui_metadata.get("mcp_app_resource_uri")
    server_id = ui_metadata.get("mcp_server_id")
    if not resource_uri or not server_id:
        return

    original_coroutine = tool.coroutine

    async def augmented_coroutine(*args, **kwargs):
        result = await original_coroutine(*args, **kwargs)
        # langchain-mcp-adapters uses response_format="content_and_artifact" so the
        # coroutine returns a (content, artifact) tuple. BaseTool.arun() then builds
        # the ToolMessage from this tuple — meaning we must inject metadata HERE,
        # before BaseTool.arun() assembles the ToolMessage.
        if isinstance(result, tuple) and len(result) == 2:
            content, artifact = result
            if isinstance(artifact, dict):
                artifact["mcp_app_resource_uri"] = resource_uri
                artifact["mcp_server_id"] = server_id
            else:
                artifact = {"mcp_app_resource_uri": resource_uri, "mcp_server_id": server_id}
            result = (content, artifact)
        elif isinstance(result, ToolMessage) and isinstance(result.artifact, dict):
            # Fallback for tools that return ToolMessage directly
            result.artifact["mcp_app_resource_uri"] = resource_uri
            result.artifact["mcp_server_id"] = server_id
        return result

    tool.coroutine = augmented_coroutine


def wrap_mcp_tool_errors(tool: Tool) -> None:
    """Wrap a tool's coroutine in-place to convert ExceptionGroup → ToolException.

    anyio task groups (used by the MCP streamable-HTTP client) surface errors as
    BaseExceptionGroup.  LangGraph's default ToolNode error handler only knows how
    to deal with ToolInvocationError and re-raises everything else, crashing the
    stream.  By converting the group to a plain ToolException here, BaseTool.arun
    catches it (because handle_tool_error=True) and returns the message as a
    regular tool result, keeping the stream alive.
    """
    original_coroutine = tool.coroutine

    async def safe_coroutine(*args, **kwargs):
        try:
            return await original_coroutine(*args, **kwargs)
        except BaseExceptionGroup as eg:
            # Unwrap nested groups to reach the root cause exception.
            inner: BaseException = eg.exceptions[0] if eg.exceptions else eg
            while isinstance(inner, BaseExceptionGroup) and inner.exceptions:
                inner = inner.exceptions[0]
            raise ToolException(str(inner)) from inner

    tool.coroutine = safe_coroutine
    tool.handle_tool_error = True
