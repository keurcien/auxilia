"""Generic tool error wrapping for LangGraph agents.

Two approaches:

1. ``wrap_tool_errors(tool)`` — wraps a single tool in-place (for tools we own).
2. ``ToolErrorMiddleware`` — middleware that catches errors from ALL tool calls,
   including tools registered by other middleware (e.g. deepagents filesystem tools).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool
from langchain_core.tools.base import ToolException
from langchain.agents.middleware.types import AgentMiddleware, ToolCallRequest
from langgraph.types import Command


class ToolErrorMiddleware(AgentMiddleware):
    """Middleware that catches uncaught exceptions from any tool call.

    Returns the error as a ToolMessage so the LLM can process it instead of
    crashing the stream.
    """

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        try:
            return await handler(request)
        except Exception as exc:
            inner = _unwrap(exc)
            return ToolMessage(
                content=f"Error: {inner}",
                tool_call_id=request.tool_call["id"],
            )


def wrap_tool_errors(tool: BaseTool) -> None:
    """Wrap a tool in-place so any exception is surfaced as a ToolMessage."""

    if tool.coroutine is not None:
        original_coroutine = tool.coroutine

        async def safe_coroutine(*args, **kwargs):
            try:
                return await original_coroutine(*args, **kwargs)
            except ToolException:
                raise
            except BaseException as exc:
                inner = _unwrap(exc)
                raise ToolException(str(inner)) from inner

        tool.coroutine = safe_coroutine

    if tool.func is not None:
        original_func = tool.func

        def safe_func(*args, **kwargs):
            try:
                return original_func(*args, **kwargs)
            except ToolException:
                raise
            except BaseException as exc:
                inner = _unwrap(exc)
                raise ToolException(str(inner)) from inner

        tool.func = safe_func

    tool.handle_tool_error = True


def _unwrap(exc: BaseException) -> BaseException:
    """Unwrap nested ExceptionGroups to get the root cause."""
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    return exc
