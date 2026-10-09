"""Block Kit builders for Slack tool messages."""

from typing import Any


def _quote_lines(lines: list[str]) -> str:
    """Join entries as a Slack blockquote, prefixing *every physical line*.

    An entry may itself span several lines (a multi-line value like formatted
    SQL, or an already-quoted nested block), so we split on newlines before
    prefixing — otherwise the quote bar drops off after the first line.
    """
    return "\n".join(f"> {physical}" for line in lines for physical in line.split("\n"))


def escape_mrkdwn(text: str) -> str:
    """Slack mrkdwn control characters, so a name renders as typed."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


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

        return _quote_lines(lines)

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
        return _quote_lines(lines)

    return "  " * indent + str(obj)


def _split_tool_name(tool_name: str) -> tuple[str, str]:
    """Split a `prefix_suffix_parts` tool name into (prefix, suffix)."""
    parts = tool_name.split("_")
    return parts[0], "_".join(parts[1:])


def format_tool_streamer_label(tool_name: str) -> str:
    """Format one compact tool-activity callout for the Slack stream.

    Server names used to be rendered as ``:server:`` custom emoji, which
    produces noisy literal mentions when a workspace has no matching emoji.
    """
    prefix, suffix = _split_tool_name(tool_name)
    return f"\n> *{escape_mrkdwn(prefix)}* › `{escape_mrkdwn(suffix)}`\n"


def build_connect_prompt_blocks(connect_url: str, app_name: str) -> list[dict]:
    """Blocks telling the user to (re)connect the agent's MCP servers on
    the configured instance. Used by handler readiness checks and the delivery
    consumer's fallback for an unexpected OAuth failure."""
    escaped_name = escape_mrkdwn(app_name)
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "I can't run this request yet because one or more MCP servers "
                    f"used by this agent are not connected for your {escaped_name} "
                    f"account. Connect the required servers in {escaped_name}, then "
                    "try again."
                ),
            },
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": f"Connect on {app_name}",
                    },
                    "url": connect_url,
                    "style": "primary",
                }
            ],
        },
    ]


def build_tool_approval_blocks(
    tool_call_id: str,
    tool_input: dict,
    interrupt_id: str | None = None,
    subagent: str | None = None,
) -> list[dict]:
    """Build Block Kit blocks for a tool approval request with Approve/Reject buttons.

    The tool name is intentionally *not* repeated here: the streamed tool label
    (`format_tool_streamer_label`) already shows it immediately above this card,
    so a header would be redundant. `subagent` names the subagent that asked,
    when one did: its tool activity is not streamed to Slack, so without it a
    card would appear to belong to the agent the user is talking to.

    The actions block carries a machine-readable ``block_id``
    (``hitl:<interrupt_id>:<tool_call_id>``) that ties the card to the
    checkpoint interrupt it answers — that id, not the card's position in the
    thread, is what the batch-resume logic keys on. `interrupt_id` is None
    only when the checkpoint didn't round-trip one; the card then falls back
    to the legacy emoji-scanned protocol.
    """
    actions_block: dict = {
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
    }
    if interrupt_id is not None:
        actions_block["block_id"] = f"hitl:{interrupt_id}:{tool_call_id}"
    blocks: list[dict] = []
    if subagent:
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"Requested by subagent *{escape_mrkdwn(subagent)}*",
                    }
                ],
            }
        )
    return [
        *blocks,
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": _format_tool_input(tool_input)},
        },
        actions_block,
        {
            "type": "divider",
        },
    ]
