from langchain_core.tools import Tool
from langchain_core.tools.base import ToolException


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
