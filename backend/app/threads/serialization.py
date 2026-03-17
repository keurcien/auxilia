"""Thread message serialization — LangGraph checkpoint → UI messages."""

import uuid
from typing import Any

from langchain_ai_sdk_adapter import to_ui_messages
from langchain_core.messages import BaseMessage, ToolMessage

from app.models.message import (
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
