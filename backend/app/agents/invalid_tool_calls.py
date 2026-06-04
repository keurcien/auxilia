"""Recover from tool calls whose arguments the model emitted as invalid JSON.

When a provider can't parse a tool call's arguments as JSON (e.g. a large
payload the model truncated or duplicated, producing "Extra data: char N"), the
provider integration routes the call to ``invalid_tool_calls`` instead of
``tool_calls``. The agent loop then sees no runnable tool call and exits to END
(see ``langchain.agents.factory._make_model_to_tools_edge``) — so the model never
learns its arguments were malformed, and the user just sees a silent stop.

``RepairInvalidToolCallsMiddleware`` runs after the model: it promotes each
invalid call to a well-formed (empty-argument) tool call, answers it with an
error ``ToolMessage`` describing the failure, and jumps back to the model so it
can read the error and try again with valid JSON.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from langchain.agents.middleware import AgentMiddleware, AgentState, hook_config
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.messages.tool import tool_call as create_tool_call
from langgraph.runtime import Runtime


logger = logging.getLogger(__name__)

# The raw malformed arguments are echoed back to the model so it can see what it
# got wrong, but a duplicated 10KB payload would needlessly bloat the next
# prompt — cap what we send back.
MAX_ECHOED_ARGS_CHARS = 2000


def _format_error(name: str, raw_args: Any, error: str | None) -> str:
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
    """Turn unparseable tool-call arguments into an error the model can recover
    from, instead of letting the agent exit the loop silently."""

    @hook_config(can_jump_to=["model"])
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

        # Keep any valid tool calls from the same turn, and promote each invalid
        # one to an empty-argument call so the assistant turn is a well-formed
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
                    content=_format_error(name, itc.get("args"), itc.get("error")),
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
        return {"messages": [repaired_ai, *tool_messages], "jump_to": "model"}
