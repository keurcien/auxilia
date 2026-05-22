"""Block Kit builders for Slack tool messages."""

from typing import Any


def _format_tool_input(obj: Any, indent: int = 0) -> str:
    """Convert a JSON-compatible object into a clean YAML-like string."""

    if obj is None:
        return "  " * indent + "~"

    if isinstance(obj, bool):
        return "  " * indent + ("true" if obj else "false")

    if isinstance(obj, (int, float)):
        return "  " * indent + str(obj)

    if isinstance(obj, str):
        return "  " * indent + obj

    if isinstance(obj, list):
        if not obj:
            return "  " * indent + "[]"
        lines = []
        for item in obj:
            if isinstance(item, dict):
                # Nested object inside list
                inner = _format_tool_input(item, indent + 2).lstrip()
                lines.append("  " * indent + "- " + inner)
            else:
                lines.append("  " * indent + "- " + str(item))

        return "\n".join(f"> {line}" for line in lines)

    if isinstance(obj, dict):
        if not obj:
            return "  " * indent + "{}"
        lines = []
        for key, value in obj.items():
            if isinstance(value, (dict, list)) and value:
                lines.append("  " * indent + "*" + key + "*:")
                lines.append(_format_tool_input(value, indent + 1))
            else:
                val_str = _format_tool_input(value, 0).strip()
                lines.append("  " * indent + "*" + key + "*: " + val_str)
        return "\n".join(f"> {line}" for line in lines)

    return "  " * indent + str(obj)


def _split_tool_name(tool_name: str) -> tuple[str, str]:
    """Split a `prefix_suffix_parts` tool name into (prefix, suffix)."""
    parts = tool_name.split("_")
    return parts[0], "_".join(parts[1:])


def format_tool_streamer_label(tool_name: str) -> str:
    """Format a tool call as Slack markdown text for the streaming chat surface.

    Returns a block with leading and trailing newlines so it slots cleanly into
    a streamer that's appending chunks of markdown.
    """
    prefix, suffix = _split_tool_name(tool_name)
    return f"\n\n:{prefix.lower()}:  **{prefix}**  ›  `{suffix}`\n\n"


def _tool_context_block(tool_name: str) -> dict:
    """Build the context block header for a tool name."""
    prefix, suffix = _split_tool_name(tool_name)
    return {
        "type": "context",
        "elements": [
            {
                "type": "mrkdwn",
                "text": f":{prefix}:  *{prefix}*  ›  `{suffix}`",
            }
        ],
    }


def build_tool_approval_blocks(
    tool_call_id: str, tool_name: str, tool_input: dict,
) -> list[dict]:
    """Build Block Kit blocks for a tool approval request with Approve/Reject buttons."""
    return [
        _tool_context_block(tool_name),
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": _format_tool_input(tool_input)},
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Approve"},
                    "style": "primary",
                    "action_id": "tool_approve",
                    "value": tool_call_id,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Reject"},
                    "style": "danger",
                    "action_id": "tool_reject",
                    "value": tool_call_id,
                },
            ],
        },
        {
            "type": "divider",
        },
    ]
