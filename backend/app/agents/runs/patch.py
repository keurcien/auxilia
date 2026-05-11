"""Append synthetic ToolMessages for AIMessage tool_calls that never got an answer.

Why this exists
---------------

When a run terminates abnormally (cancellation, instance death, crash) while a
tool is in flight, the LangGraph checkpoint is left with an ``AIMessage`` whose
``tool_calls`` have no corresponding ``ToolMessage``. The UI shows those tools
as a permanently-spinning "pending" state, and the LLM cannot continue from
that thread — every provider rejects an assistant turn with unanswered tool
calls.

deepagents ships ``PatchToolCallsMiddleware`` that fixes this on the *next*
``before_agent``, but by then the user has been staring at a stuck spinner. We
need to call the same logic explicitly at the *end* of an aborted run, so the
thread is consistent the moment the run terminates.

This module is the one place that knows the synthetic-message format. If
deepagents ever exposes an ``on_cancel`` hook upstream, this file is the
single deletion point.

Idempotency
-----------

``patch_dangling_tool_calls`` re-reads checkpoint state on every call and only
synthesises messages for tool_calls that are still unanswered. Calling it
twice in quick succession (e.g. cancel signal + reaper picking up the same
run) writes the synthetic messages exactly once.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage


DEFAULT_CANCEL_REASON: str = (
    "Run terminated before this tool could complete. "
    "Please retry or reformulate your request."
)


def find_dangling_tool_calls(
    messages: list[BaseMessage],
    *,
    reason: str = DEFAULT_CANCEL_REASON,
) -> list[ToolMessage]:
    """Return synthetic ``ToolMessage`` entries for unanswered tool_calls.

    Pure function: takes a message list, returns what should be appended.
    Worker / reaper / service all use this through ``patch_dangling_tool_calls``.
    """
    answered_ids: set[str] = set()
    for msg in messages:
        if isinstance(msg, ToolMessage) and msg.tool_call_id:
            answered_ids.add(msg.tool_call_id)

    patches: list[ToolMessage] = []
    for msg in messages:
        if not isinstance(msg, AIMessage):
            continue
        if not msg.tool_calls:
            continue
        for tc in msg.tool_calls:
            tc_id = tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", None)
            if not tc_id or tc_id in answered_ids:
                continue
            tc_name = (
                tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None)
            )
            patches.append(
                ToolMessage(
                    content=(
                        f"Tool call {tc_name} with id {tc_id} was cancelled — {reason}"
                    ),
                    name=tc_name,
                    tool_call_id=tc_id,
                    status="error",
                )
            )
            # Mark as patched so we don't synthesise twice if the same id
            # appears in multiple AIMessage entries (defensive — shouldn't happen).
            answered_ids.add(tc_id)
    return patches


async def patch_dangling_tool_calls(
    graph,
    config: dict,
    *,
    reason: str = DEFAULT_CANCEL_REASON,
) -> int:
    """Read the thread state through ``graph``, append patches, return count.

    ``graph`` is a compiled LangGraph state graph with a checkpointer attached
    (typically the same agent instance the run was using). ``config`` is the
    LangGraph runnable config carrying ``thread_id``.

    Returns the number of synthetic messages written.
    """
    state = await graph.aget_state(config)
    messages = state.values.get("messages", []) if state and state.values else []
    patches = find_dangling_tool_calls(messages, reason=reason)
    if patches:
        await graph.aupdate_state(config, {"messages": patches})
    return len(patches)
