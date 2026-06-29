"""Thread message serialization — LangGraph checkpoint → UI messages."""

import uuid
from typing import Any

from langchain_ai_sdk_adapter import to_ui_messages
from langchain_core.messages import BaseMessage, ToolMessage

from app.models import (
    FileMessagePart,
    Message,
    ReasoningMessagePart,
    TextMessagePart,
    ToolMessagePart,
)


def _build_tool_metadata_map(
    lc_messages: list[BaseMessage],
) -> dict[str, dict[str, Any]]:
    """Build a map from tool_call_id → callProviderMetadata from ToolMessage artifacts."""
    metadata: dict[str, dict[str, Any]] = {}
    for msg in lc_messages:
        if isinstance(msg, ToolMessage):
            tc_id = getattr(msg, "tool_call_id", None)
            artifact = getattr(msg, "artifact", None)
            if tc_id and isinstance(artifact, dict):
                uri = artifact.get("mcp_app_resource_uri")
                sid = artifact.get("mcp_server_id")
                if uri and sid:
                    metadata[tc_id] = {
                        "auxilia": {
                            "mcpAppResourceUri": uri,
                            "mcpServerId": sid,
                        }
                    }
    return metadata


def _convert_part(
    part: dict[str, Any], tool_metadata: dict[str, dict[str, Any]]
) -> TextMessagePart | ReasoningMessagePart | FileMessagePart | ToolMessagePart | None:
    """Convert a library UI part dict to an auxilia MessagePart."""
    ptype = part.get("type", "")

    if ptype == "text":
        return TextMessagePart(text=part.get("text", ""))

    if ptype == "reasoning":
        return ReasoningMessagePart(text=part.get("text", ""))

    if ptype == "file":
        return FileMessagePart(
            url=part.get("url", ""),
            filename=part.get("filename"),
            mediaType=part.get("mediaType"),
        )

    if ptype == "tool-invocation":
        tc_id = part.get("toolInvocationId", "")
        tc_name = part.get("toolName", "")
        state = part.get("state", "call")

        if state == "result":
            return ToolMessagePart(
                type=f"tool-{tc_name}",
                toolCallId=tc_id,
                toolName=tc_name,
                state="output-available",
                input=part.get("args"),
                output=part.get("result"),
                callProviderMetadata=tool_metadata.get(tc_id),
            )

        if state == "error":
            error_text = part.get("error", "Tool execution failed")
            if "rejected" in error_text.lower() or "denied" in error_text.lower():
                error_text = "Tool execution was rejected by user"
            return ToolMessagePart(
                type=f"tool-{tc_name}",
                toolCallId=tc_id,
                toolName=tc_name,
                state="output-error",
                input=part.get("args"),
                errorText=error_text,
                callProviderMetadata=tool_metadata.get(tc_id),
            )

        # state == "call" (no result yet)
        return ToolMessagePart(
            type=f"tool-{tc_name}",
            toolCallId=tc_id,
            toolName=tc_name,
            state="output-error",
            input=part.get("args"),
            callProviderMetadata=tool_metadata.get(tc_id),
        )

    return None


def pending_interrupt(checkpoint_tuple: Any) -> Any | None:
    """Return the pending HITL interrupt value from a checkpoint tuple, or None.

    A graph paused on `HumanInTheLoopMiddleware` leaves an `__interrupt__` entry
    in the checkpoint's `pending_writes`; this extracts its value. Shared by the
    thread read endpoint and the durable runtime's terminal-status detection.
    """
    for _, channel, value in getattr(checkpoint_tuple, "pending_writes", None) or []:
        if channel != "__interrupt__":
            continue
        batch = value if isinstance(value, (list, tuple)) else [value]
        if not batch:
            continue
        first = batch[0]
        return getattr(first, "value", first)
    return None


def pending_approval_requests(checkpoint_tuple: Any) -> list[dict[str, Any]]:
    """Return the tool calls awaiting human approval on a paused checkpoint.

    `HumanInTheLoopMiddleware` interrupts with a `HITLRequest` whose
    `action_requests` carry only `name`/`args` (no id), and resume `decisions`
    are positional. We re-attach each request to the originating tool call (by
    name+args, falling back to position) so callers get a stable
    `tool_call_id` for the approve/reject UI. Returns `[]` when not interrupted.
    """
    interrupt_value = pending_interrupt(checkpoint_tuple)
    requests = (
        (interrupt_value or {}).get("action_requests")
        if (isinstance(interrupt_value, dict))
        else None
    )
    if not requests:
        return []

    channel_values = getattr(checkpoint_tuple, "checkpoint", {}).get(
        "channel_values", {}
    )
    tool_calls = _last_pending_tool_calls(channel_values.get("messages", []))

    approvals: list[dict[str, Any]] = []
    used: set[int] = set()
    for index, request in enumerate(requests):
        match = _match_tool_call(request, tool_calls, used)
        approvals.append(
            {
                "tool_call_id": (match or {}).get("id") or f"approval-{index}",
                "tool_name": request.get("name", "unknown"),
                "input": request.get("args", {}),
            }
        )
    return approvals


def _last_pending_tool_calls(messages: list) -> list[dict[str, Any]]:
    """Tool calls on the last AI message that have no result yet."""
    resulted = {
        getattr(m, "tool_call_id", None) for m in messages if isinstance(m, ToolMessage)
    }
    for msg in reversed(messages):
        tool_calls = getattr(msg, "tool_calls", None)
        if tool_calls:
            return [tc for tc in tool_calls if tc.get("id") not in resulted]
    return []


def _match_tool_call(
    request: dict, tool_calls: list[dict], used: set[int]
) -> dict | None:
    """Find the unused tool call for an action request.

    Prefers an exact name+args match; falls back to the first unused call with
    the same name (covers two calls to the same tool with identical args).
    """
    candidates = [
        (i, tc)
        for i, tc in enumerate(tool_calls)
        if i not in used and tc.get("name") == request.get("name")
    ]
    if not candidates:
        return None
    for i, tc in candidates:
        if tc.get("args") == request.get("args"):
            used.add(i)
            return tc
    i, tc = candidates[0]
    used.add(i)
    return tc


def deserialize_to_ui_messages(langgraph_messages: list) -> list[Message]:
    """Convert LangGraph checkpoint messages to auxilia UI messages.

    Uses the library's to_ui_messages() for core conversion (grouping,
    content extraction, structured content), then enriches with
    auxilia-specific metadata (callProviderMetadata from artifacts).
    """
    ui_dicts = to_ui_messages(langgraph_messages)
    tool_metadata = _build_tool_metadata_map(langgraph_messages)

    messages = []
    for msg_dict in ui_dicts:
        parts = []
        for p in msg_dict.get("parts", []):
            converted = _convert_part(p, tool_metadata)
            if converted is not None:
                parts.append(converted)
        if parts:
            messages.append(
                Message(id=str(uuid.uuid4()), role=msg_dict["role"], parts=parts)
            )

    return messages
