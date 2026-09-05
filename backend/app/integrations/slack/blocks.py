"""Block Kit builders for Slack tool messages."""

from typing import Any


def _quote_lines(lines: list[str]) -> str:
    """Join entries as a Slack blockquote, prefixing *every physical line*.

    An entry may itself span several lines (a multi-line value like formatted
    SQL, or an already-quoted nested block), so we split on newlines before
    prefixing — otherwise the quote bar drops off after the first line.
    """
    return "\n".join(f"> {physical}" for line in lines for physical in line.split("\n"))


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
    """Format a tool call as Slack markdown text for the streaming chat surface.

    Returns a block with leading and trailing newlines so it slots cleanly into
    a streamer that's appending chunks of markdown.
    """
    prefix, suffix = _split_tool_name(tool_name)
    return f"\n\n:{prefix.lower()}:  **{prefix}**  ›  `{suffix}`\n\n"


def build_connect_prompt_blocks(connect_url: str) -> list[dict]:
    """Blocks telling the user to (re)connect the agent's MCP servers on
    auxilia. Used by the pre-enqueue gates (handlers) and by the delivery
    consumer when the worker's OAuth pre-flight refused an already-enqueued
    run."""
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "Agent is not configured or agent requires authentication on your behalf. Please sign in to auxilia to continue.",
            },
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Connect on auxilia"},
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
                    {"type": "mrkdwn", "text": f"Requested by subagent *{subagent}*"}
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
