"""HITL (Human-in-the-Loop) approval extraction from UI messages."""

from app.models.message import Message, ToolMessagePart


def _is_pending_approval(part: ToolMessagePart) -> bool:
    """Check if a tool part has a pending approval (not yet processed)."""
    if part.approval is None:
        return False
    if part.state != "approval-responded":
        return False
    if part.output is not None or part.errorText is not None:
        return False
    return True


def extract_commands(message: Message) -> list[str] | None:
    """Extract approval commands (approve/reject) from PENDING tool message parts."""
    commands = []

    if hasattr(message, "parts") and message.parts:
        for part in message.parts:
            if isinstance(part, ToolMessagePart) and _is_pending_approval(part):
                commands.append("approve" if part.approval["approved"] else "reject")

    return commands if len(commands) > 0 else None


def extract_rejected_tool_calls(message: Message) -> list[dict]:
    """Extract PENDING tool calls that were rejected by the user."""
    rejected = []

    if hasattr(message, "parts") and message.parts:
        for part in message.parts:
            if isinstance(part, ToolMessagePart) and _is_pending_approval(part):
                if not part.approval.get("approved", True):
                    rejected.append(
                        {
                            "toolCallId": part.toolCallId,
                            "toolName": part.toolName,
                            "reason": part.approval.get(
                                "reason", "Tool execution was rejected by user"
                            ),
                        }
                    )

    return rejected


def extract_approved_tool_call_ids(message: Message) -> list[str]:
    """Extract tool call IDs that were approved by the user (pending)."""
    approved_ids = []

    if hasattr(message, "parts") and message.parts:
        for part in message.parts:
            if isinstance(part, ToolMessagePart) and _is_pending_approval(part):
                if part.approval.get("approved", False):
                    approved_ids.append(part.toolCallId)

    return approved_ids
