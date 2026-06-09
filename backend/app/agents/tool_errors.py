"""Turn tool-call problems into ToolMessages the model can recover from.

Three mechanisms, all so a tool failure feeds back to the LLM instead of
crashing the stream or silently ending the run:

1. ``wrap_tool_errors(tool)`` — wraps a single tool in-place (for tools we own),
   surfacing execution exceptions as a ToolMessage.
2. ``ToolErrorMiddleware`` — catches execution exceptions from ALL tool calls,
   including tools registered by other middleware (e.g. deepagents filesystem
   tools).
3. ``RepairInvalidToolCallsMiddleware`` — handles the case *before* execution,
   where the model emitted arguments that aren't valid JSON: it answers each
   such call with an error ToolMessage so the model can retry with valid JSON.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4

from langchain.agents.middleware.types import (
    AgentMiddleware,
    AgentState,
    ToolCallRequest,
)
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.messages.tool import tool_call as create_tool_call
from langchain_core.tools import BaseTool
from langchain_core.tools.base import ToolException
from langgraph.runtime import Runtime
from langgraph.types import Command


logger = logging.getLogger(__name__)


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


# The raw malformed arguments are echoed back to the model so it can see what it
# got wrong, but a duplicated 10KB payload would needlessly bloat the next
# prompt — cap what we send back.
MAX_ECHOED_ARGS_CHARS = 2000


def _format_invalid_args_error(name: str, raw_args: Any, error: str | None) -> str:
    """Tool-result text telling the model why its arguments were rejected."""
    raw = raw_args if isinstance(raw_args, str) else str(raw_args)
    if len(raw) > MAX_ECHOED_ARGS_CHARS:
        raw = f"{raw[:MAX_ECHOED_ARGS_CHARS]}… [truncated, {len(raw)} chars total]"
    detail = f" ({error})" if error else ""
    return (
        f"Error: the arguments for `{name}` were not valid JSON and could not be "
        f"parsed{detail}, so the tool did not run. This usually means the JSON was "
        "truncated or duplicated. Call the tool again with a single, complete, "
        "valid JSON object. If the payload is large, split it into several smaller "
        f"calls.\n\nRaw arguments received:\n{raw}"
    )


class RepairInvalidToolCallsMiddleware(AgentMiddleware):
    """Recover from tool calls whose arguments the model emitted as invalid JSON.

    When a provider can't parse a tool call's arguments as JSON (e.g. a large
    payload the model truncated or duplicated, producing "Extra data: char N"),
    the provider integration routes the call to ``invalid_tool_calls`` instead of
    ``tool_calls``. The agent loop then sees no runnable tool call and exits to
    END (see ``langchain.agents.factory._make_model_to_tools_edge``) — so the
    model never learns its arguments were malformed, and the user just sees a
    silent stop.

    This ``after_model`` hook promotes each invalid call to a well-formed
    (empty-argument) tool call and answers it with an error ``ToolMessage``. It
    does *not* force a route — it returns the state update and lets the normal
    model→tools edge take over:

    - Genuinely valid tool calls in the same turn stay pending (no answer yet) and
      get executed normally; the promoted-invalid calls already have their error
      ``ToolMessage`` so they're skipped.
    - When every call was invalid, nothing is pending, so the edge routes back to
      the model — which reads the errors and retries with valid JSON.

    Must run *after* ``HumanInTheLoopMiddleware`` (i.e. placed before it in the
    middleware list, since ``after_model`` hooks execute last-to-first). HITL
    gates calls by name without checking whether they already have a response, so
    it must see only the real ``tool_calls`` — the invalid calls stay in
    ``invalid_tool_calls`` (invisible to HITL) until this middleware promotes them.
    """

    def after_model(
        self,
        state: AgentState,
        runtime: Runtime[Any],  # noqa: ARG002 - required by hook signature
    ) -> dict[str, Any] | None:
        messages = state["messages"]
        if not messages:
            return None
        last = messages[-1]
        if not isinstance(last, AIMessage) or not last.invalid_tool_calls:
            return None

        # Keep any valid tool calls from the same turn (they stay pending and the
        # model→tools edge will still execute them), and promote each invalid one
        # to an empty-argument call so the assistant turn is a well-formed
        # tool_use that the matching error ToolMessage can answer. (Anthropic's
        # _format_messages dedupes tool_use blocks by id, so the original
        # malformed payload in the message content is dropped on the round-trip.)
        repaired_calls = list(last.tool_calls)
        tool_messages: list[ToolMessage] = []
        for itc in last.invalid_tool_calls:
            name = itc.get("name") or "unknown"
            tc_id = itc.get("id") or str(uuid4())
            repaired_calls.append(create_tool_call(name=name, args={}, id=tc_id))
            tool_messages.append(
                ToolMessage(
                    content=_format_invalid_args_error(
                        name, itc.get("args"), itc.get("error")
                    ),
                    name=name,
                    tool_call_id=tc_id,
                    status="error",
                )
            )

        logger.warning(
            "Repaired %d invalid tool call(s) on message %s (%s); returning error "
            "to the model for retry",
            len(tool_messages),
            last.id,
            ", ".join(tc.name for tc in tool_messages),
        )

        repaired_ai = last.model_copy(
            update={"tool_calls": repaired_calls, "invalid_tool_calls": []}
        )
        # No explicit jump: the normal model→tools edge runs any still-pending
        # (valid) calls, then loops back to the model; if every call was invalid
        # there's nothing pending so it routes straight back to the model.
        return {"messages": [repaired_ai, *tool_messages]}


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
