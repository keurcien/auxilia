import json
import uuid
import logging
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from app.models.message import Message, TextMessagePart, ToolMessagePart, ReasoningMessagePart, FileMessagePart

import logging


def to_langchain_file_part(file_part) -> dict | None:
    try:
        m_type = getattr(file_part, 'mediaType', 'unknown')
        url = getattr(file_part, 'url', '')

        base64_data = url.split(',', 1)[1] if ',' in url else url

        if m_type.startswith('image/'):
            return {
                "type": "image",
                "source_type": "base64",
                "data": base64_data,
                "filename": file_part.filename,
                "mime_type": m_type,
                "source": {
                    "type": "base64",
                    "media_type": m_type,
                    "data": base64_data,
                }
            }

        elif any(t in m_type for t in ['pdf', 'text', 'csv']):
            return {
                "type": "file",
                "source_type": "base64",
                "filename": file_part.filename,
                "mime_type": m_type,
                "data": base64_data,
                "source": {
                    "type": "base64",
                    "media_type": m_type,
                    "data": base64_data,
                }
            }

        return None

    except Exception as e:
        logging.error(f"Error converting file part: {e}")
        return None


def extract_text_content(message: Message) -> list[str]:
    """Extract text content from message parts."""
    content_parts = []

    if hasattr(message, "parts") and message.parts:
        for part in message.parts:
            if part.type == "text":
                content_parts.append(part.text)

    elif hasattr(message, "content") and message.content:
        content_parts.append(message.content)

    content = " ".join(content_parts)
    return {"type": "text", "text": content}


def extract_file_content(message: Message) -> list[str]:
    """Extract file content from message parts."""
    file_parts = []
    if hasattr(message, "parts") and message.parts:
        for part in message.parts:
            if part.type == "file":
                file_parts.append(part)
    return file_parts


def _is_pending_approval(part: ToolMessagePart) -> bool:
    """Check if a tool part has a pending approval (not yet processed)."""
    # Must have an approval response
    if part.approval is None:
        return False
    # Must be in approval-responded state (just responded, not processed yet)
    # Other states like output-available, output-error mean it's already processed
    if part.state != "approval-responded":
        return False
    # Must NOT have output or error (double-check it hasn't been processed)
    if part.output is not None or part.errorText is not None:
        return False
    return True


def extract_commands(message: Message) -> list[str] | None:
    """Extract approval commands (approve/reject) from PENDING tool message parts.

    Only extracts commands for tools that have an approval response but haven't
    been processed yet (no output or error).
    """
    commands = []

    if hasattr(message, "parts") and message.parts:
        for part in message.parts:
            if isinstance(part, ToolMessagePart) and _is_pending_approval(part):
                commands.append(
                    "approve" if part.approval["approved"] else "reject")

    return commands if len(commands) > 0 else None


def extract_rejected_tool_calls(message: Message) -> list[dict]:
    """Extract PENDING tool calls that were rejected by the user.

    Only extracts rejections for tools that haven't been processed yet.
    """
    rejected = []

    if hasattr(message, "parts") and message.parts:
        for part in message.parts:
            if isinstance(part, ToolMessagePart) and _is_pending_approval(part):
                if not part.approval.get("approved", True):
                    rejected.append({
                        "toolCallId": part.toolCallId,
                        "toolName": part.toolName,
                        "reason": part.approval.get("reason", "Tool execution was rejected by user"),
                    })

    return rejected


def extract_approved_tool_call_ids(message: Message) -> list[str]:
    """Extract tool call IDs that were approved by the user (pending).

    Only extracts approvals for tools that haven't been processed yet.
    """
    approved_ids = []

    if hasattr(message, "parts") and message.parts:
        for part in message.parts:
            if isinstance(part, ToolMessagePart) and _is_pending_approval(part):
                if part.approval.get("approved", False):
                    approved_ids.append(part.toolCallId)

    return approved_ids


def to_langchain_message(message: Message) -> HumanMessage:
    """
    Convert AI SDK v5 messages to LangChain HumanMessage format.

    Args:
        message: AI SDK Message object

    Returns:
        LangChain HumanMessage object
    """
    content = [extract_text_content(message)]
    file_parts = extract_file_content(message)

    for file_part in file_parts:
        content.append(to_langchain_file_part(file_part))

    return HumanMessage(content=content)


def deserialize_to_ui_messages(langgraph_messages: list) -> list[Message]:
    print(langgraph_messages)
    ui_messages = []
    i = 0

    while i < len(langgraph_messages):
        msg = langgraph_messages[i]
        role = None
        parts = []

        if isinstance(msg, HumanMessage):
            role = "user"
            if hasattr(msg, "content") and msg.content:
                if isinstance(msg.content, str):
                    parts.append(TextMessagePart(text=msg.content))
                # Process file parts first, then text parts to match AI SDK streaming order
                elif isinstance(msg.content, list):
                    text_parts = []
                    file_parts = []
                    for content_item in msg.content:
                        if isinstance(content_item, str):
                            text_parts.append(
                                TextMessagePart(text=content_item))
                        elif isinstance(content_item, dict):
                            item_type = content_item.get("type")
                            if item_type == "text":
                                text_parts.append(TextMessagePart(
                                    text=content_item.get("text", "")))
                            elif item_type == "image" or item_type == "file":
                                file_parts.append(
                                    FileMessagePart(
                                        type="file",
                                        url=content_item.get(
                                            "source", {}).get("data", ""),
                                        filename=content_item.get(
                                            "filename", ""),
                                        mediaType=content_item.get(
                                            "source", {}).get("media_type", ""),
                                    )
                                )

                    parts.extend(file_parts)
                    parts.extend(text_parts)

            i += 1

        elif isinstance(msg, AIMessage):
            role = "assistant"

            # This loop groups the AI Message + its following Tool Messages into one UI block
            while i < len(langgraph_messages) and (
                isinstance(langgraph_messages[i], AIMessage)
                or isinstance(langgraph_messages[i], ToolMessage)
            ):
                current_msg = langgraph_messages[i]

                if isinstance(current_msg, AIMessage):
                    # 1. Handle Text Content
                    if hasattr(current_msg, "content") and current_msg.content:
                        if isinstance(current_msg.content, str):
                            parts.append(TextMessagePart(
                                text=current_msg.content))
                        elif isinstance(current_msg.content, list):
                            for item in current_msg.content:
                                if isinstance(item, dict):
                                    if item.get("type") == "thinking" and "thinking" in item:
                                        # Handle thinking/reasoning content
                                        parts.append(ReasoningMessagePart(
                                            type="reasoning", text=item["thinking"]))
                                    elif "text" in item:
                                        parts.append(
                                            TextMessagePart(text=item["text"]))
                                elif isinstance(item, str):
                                    parts.append(TextMessagePart(text=item))

                    # 2. Handle Tool Calls (EXACT LOGIC FROM YOUR SNIPPET)
                    if hasattr(current_msg, "tool_calls") and current_msg.tool_calls:
                        # Create a map of tool call ID to tool result for quick lookup
                        tool_results = {}

                        # Look ahead for ToolMessage results that correspond to these tool calls
                        j = i + 1
                        while j < len(langgraph_messages):
                            next_msg = langgraph_messages[j]
                            if isinstance(next_msg, ToolMessage):
                                # Robust retrieval of tool_call_id
                                tool_call_id = getattr(
                                    next_msg, "tool_call_id", None)
                                if tool_call_id is None and hasattr(
                                    next_msg, "__dict__"
                                ):
                                    tool_call_id = next_msg.__dict__.get(
                                        "tool_call_id", None
                                    )

                                if tool_call_id:
                                    # Try to parse JSON if possible for the result
                                    content = next_msg.content
                                    try:
                                        content = json.loads(content)
                                    except (TypeError, json.JSONDecodeError):
                                        pass

                                    # Get the status (success or error) from ToolMessage
                                    status = getattr(
                                        next_msg, "status", "success")

                                    # Reconstruct callProviderMetadata from artifact
                                    # (injected at execution time by inject_ui_metadata_into_tool)
                                    call_provider_metadata = None
                                    artifact = getattr(
                                        next_msg, "artifact", None)
                                    if isinstance(artifact, dict):
                                        resource_uri = artifact.get(
                                            "mcp_app_resource_uri")
                                        server_id = artifact.get(
                                            "mcp_server_id")
                                        if resource_uri and server_id:
                                            call_provider_metadata = {
                                                "auxilia": {
                                                    "mcpAppResourceUri": resource_uri,
                                                    "mcpServerId": server_id,
                                                }
                                            }

                                    tool_results[tool_call_id] = {
                                        "content": content,
                                        "status": status,
                                        "call_provider_metadata": call_provider_metadata,
                                    }
                                j += 1
                            else:
                                break

                        # Create tool parts with both input and output
                        for tool_call in current_msg.tool_calls:
                            # Handle object vs dict access for tool_call
                            if isinstance(tool_call, dict):
                                tool_name = tool_call.get("name", "unknown")
                                tool_id = tool_call.get("id", "unknown")
                                tool_args = tool_call.get("args", {})
                            else:
                                tool_name = getattr(
                                    tool_call, "name", "unknown")
                                tool_id = getattr(tool_call, "id", "unknown")
                                tool_args = getattr(tool_call, "args", {})

                            # Check if we have a result for this tool call
                            tool_result = tool_results.get(tool_id)
                            tool_output = None
                            tool_status = "success"

                            if tool_result:
                                tool_output = tool_result.get("content")
                                tool_status = tool_result.get(
                                    "status", "success")

                            if isinstance(tool_output, list) and len(tool_output) > 0:
                                tool_output = tool_output[0].get("text")

                            try:
                                tool_output = json.loads(tool_output)
                            except:
                                pass

                            # Set state based on status and presence of output
                            if tool_output is None:
                                tool_state = "output-error"
                            elif tool_status == "error":
                                tool_state = "output-error"
                            else:
                                tool_state = "output-available"

                            # TO BE REFACTORED
                            # For errors, use a clean message consistent with streaming
                            error_text = None
                            if tool_state == "output-error":
                                output_str = str(
                                    tool_output) if tool_output else ""
                                if "rejected" in output_str.lower() or "denied" in output_str.lower():
                                    error_text = "Tool execution was rejected by user"
                                else:
                                    error_text = output_str

                            tool_part = ToolMessagePart(
                                type=f"tool-{tool_name}",
                                toolCallId=tool_id,
                                toolName=tool_name,
                                state=tool_state,
                                input=tool_args,
                                output=tool_output if tool_state == "output-available" else None,
                                errorText=error_text,
                                callProviderMetadata=tool_result.get(
                                    "call_provider_metadata") if tool_result else None,
                            )
                            parts.append(tool_part)

                elif isinstance(current_msg, ToolMessage):
                    # ToolMessages are already processed via the look-ahead in the AIMessage block
                    pass

                i += 1

        elif isinstance(msg, SystemMessage):
            role = "system"
            if hasattr(msg, "content") and msg.content:
                parts.append(TextMessagePart(text=str(msg.content)))
            i += 1

        else:
            # Skip unknown types
            i += 1
            continue

        # Construct the final UI Message if we found valid parts
        if role and parts:
            ui_messages.append(
                Message(id=str(uuid.uuid4()), role=role, parts=parts))

    return ui_messages
