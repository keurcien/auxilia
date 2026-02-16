# Handlers contain the business logic for each Slack event type.
#
# Threads are created when the user picks an agent via the agent picker
# (triggered by @auxilia mention).  Subsequent messages in that thread
# are routed to the configured agent.

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from slack_sdk.web.async_client import AsyncWebClient
from langchain.messages import HumanMessage
from app.integrations.slack.models import SlackEvent, SlackInteractionPayload
from app.integrations.slack.settings import slack_settings
from app.integrations.slack.utils import get_user_info
from app.users.models import UserDB
from app.users.service import get_user_by_email
from app.database import AsyncSessionLocal
from app.agents.runtime import AgentRuntime, build_agent_deps
from app.integrations.slack.blocks import build_tool_approval_blocks
from app.integrations.slack.commands.chat import post_agent_picker
from app.threads.models import ThreadDB


SLACK_POST_MESSAGE_URL = "https://slack.com/api/chat.postMessage"


async def send_slack_message(channel: str, thread_ts: str, text: str) -> None:
    """Post a message to a Slack channel/thread."""
    async with httpx.AsyncClient() as client:
        await client.post(
            SLACK_POST_MESSAGE_URL,
            headers={"Authorization": f"Bearer {slack_settings.slack_bot_token}"},
            json={"channel": channel, "text": text, "thread_ts": thread_ts},
        )


async def resolve_user(slack_user_id: str) -> UserDB | None:
    """Map a Slack user ID to an internal user via email lookup."""
    user_info = await get_user_info(slack_user_id)
    if not user_info or not user_info.profile.email:
        return None
    async with AsyncSessionLocal() as db:
        return await get_user_by_email(user_info.profile.email, db)


async def post_tool_approval_block(
    client: AsyncWebClient, channel: str, thread_ts: str, ev: dict,
) -> None:
    """Post a tool approval request as a Block Kit message with Approve/Reject buttons."""
    blocks = build_tool_approval_blocks(
        ev["tool_call_id"], ev["tool_name"], ev["input"])
    await client.chat_postMessage(
        channel=channel, thread_ts=thread_ts,
        blocks=blocks, text=f"Approve {ev['tool_name']}?",
    )


async def _stream_and_collect_approvals(
    agent_runtime: AgentRuntime,
    streamer,
    *,
    messages: list | None = None,
    commands: list[str] | None = None,
) -> list[dict]:
    """Stream the agent response, forwarding text to the streamer.

    Returns a list of ``tool_approval_request`` events collected during
    the stream (empty when none were emitted).
    """
    approval_requests: list[dict] = []

    stream_kwargs: dict = {"stream_adapter": "slack"}
    if commands is not None:
        stream_kwargs["messages"] = []
        stream_kwargs["commands"] = commands
    else:
        stream_kwargs["messages"] = messages or []

    async for ev in agent_runtime.stream(**stream_kwargs):
        if ev["type"] == "text":
            await streamer.append(markdown_text=ev["content"])
        elif ev["type"] == "tool_approval_request":
            approval_requests.append(ev)

    await streamer.stop()
    return approval_requests


# ---------------------------------------------------------------------------
# Approval-message introspection  (stateless — reads from the thread itself)
# ---------------------------------------------------------------------------

def _is_pending(msg: dict) -> bool:
    """Check if a message still has approval action buttons."""
    for block in msg.get("blocks", []):
        if block.get("type") == "actions" and any(
            el.get("action_id") in ("tool_approve", "tool_reject")
            for el in block.get("elements", [])
        ):
            return True
    return False


def _extract_decision(msg: dict) -> str | None:
    """Extract the decision from a decided approval message."""
    for block in msg.get("blocks", []):
        if block.get("type") != "context":
            continue
        for el in block.get("elements", []):
            text = el.get("text", "")
            if ":white_check_mark:" in text:
                return "approve"
            if ":no_entry_sign:" in text:
                return "reject"
    return None


def _is_approval_message(msg: dict) -> bool:
    """Check if a message is an approval block (pending or decided)."""
    return _is_pending(msg) or _extract_decision(msg) is not None


def _get_latest_approval_batch(messages: list[dict]) -> list[dict]:
    """Return the trailing group of consecutive approval messages.

    Scans from the end of the thread backwards and collects all
    contiguous approval messages (pending or decided). Stops at
    the first non-approval message.
    """
    batch: list[dict] = []
    for msg in reversed(messages):
        if _is_approval_message(msg):
            batch.append(msg)
        else:
            if batch:
                break
    batch.reverse()
    return batch


def _collect_batch_decisions(thread_messages: list[dict]) -> list[str] | None:
    """Inspect the thread and return decisions if the latest batch is complete.

    Returns ``None`` if there are still pending approvals, or if no
    decided approvals were found.
    """
    batch = _get_latest_approval_batch(thread_messages)

    if any(_is_pending(msg) for msg in batch):
        return None

    commands = [d for msg in batch if (
        d := _extract_decision(msg)) is not None]
    return commands or None


async def _update_approval_message(
    client: AsyncWebClient, channel_id: str, message_ts: str,
    blocks: list[dict], approved: bool,
) -> None:
    """Update the approval message: append decision to header, remove buttons, add divider."""
    status_emoji = ":white_check_mark:" if approved else ":no_entry_sign:"
    status_label = "Approved" if approved else "Rejected"

    updated_blocks: list[dict] = []
    for block in blocks:
        if block.get("type") == "actions":
            continue

        if block.get("type") == "context" and not any(
            status in el.get("text", "")
            for el in block.get("elements", [])
            for status in (":white_check_mark:", ":no_entry_sign:")
        ):
            elements = block.get("elements", [])
            if elements and elements[0].get("type") == "mrkdwn":
                block = {
                    **block,
                    "elements": [{
                        **elements[0],
                        "text": f"{elements[0]['text']}  ›  {status_emoji} {status_label}",
                    }],
                }
        updated_blocks.append(block)

    await client.chat_update(
        channel=channel_id, ts=message_ts,
        blocks=updated_blocks, text=status_label,
    )


# ---------------------------------------------------------------------------
# Top-level event handlers
# ---------------------------------------------------------------------------

async def stream_agent_response(
    thread: ThreadDB,
    db: AsyncSession,
    question: str,
    event: SlackEvent,
    client: AsyncWebClient,
    *,
    team_id: str | None = None,
) -> None:
    """Build the agent runtime, stream the response, and close the streamer."""
    streamer = await client.chat_stream(
        channel=event.channel,
        thread_ts=event.thread_ts or event.ts,
        recipient_team_id=team_id,
        recipient_user_id=event.user,
    )
    thread_ts = event.thread_ts or event.ts

    deps = build_agent_deps(thread, db)
    agent_runtime = await AgentRuntime.create(thread=thread, db=db, deps=deps)

    approval_requests = await _stream_and_collect_approvals(
        agent_runtime, streamer,
        messages=[HumanMessage(content=question)],
    )

    for req in approval_requests:
        await post_tool_approval_block(client, event.channel, thread_ts, req)


async def handle_message(event: SlackEvent, *, team_id: str | None = None) -> None:
    """Route a Slack message to the configured agent for this thread."""
    thread_ts = event.thread_ts or event.ts
    question = (event.text or "").strip()
    if not question:
        return

    client = AsyncWebClient(token=slack_settings.slack_bot_token)

    # Look up the existing thread (created when the user picked an agent)
    db = AsyncSessionLocal()
    thread = await db.get(ThreadDB, thread_ts)

    if not thread:
        await db.close()
        await post_agent_picker(client, event.channel, thread_ts)
        return

    await client.assistant_threads_setStatus(
        channel_id=event.channel, thread_ts=thread_ts, status="is typing...",
    )

    await stream_agent_response(
        thread, db, question, event, client, team_id=team_id,
    )


async def handle_interaction(payload: SlackInteractionPayload) -> None:
    """Handle a Slack block_actions interaction (Approve/Reject buttons).

    Uses ``conversations.replies`` to derive approval state from the thread
    itself — no external state store needed.  The agent is only resumed
    once every pending tool call has been decided.
    """
    if not payload.actions:
        return

    action = payload.actions[0]
    if action.action_id not in ("tool_approve", "tool_reject"):
        return

    approved = action.action_id == "tool_approve"
    channel_id, thread_ts, message_ts = _extract_interaction_context(payload)
    if not channel_id or not thread_ts:
        return

    client = AsyncWebClient(token=slack_settings.slack_bot_token)

    # Update the clicked message: buttons → status label
    if message_ts:
        original_blocks = payload.message.blocks if payload.message else []
        await _update_approval_message(
            client, channel_id, message_ts, original_blocks, approved,
        )

    # Check whether the latest batch of approvals is fully decided
    commands = await _fetch_and_resolve_decisions(client, channel_id, thread_ts)
    if commands is None:
        return

    # All decided — resume the agent
    await _resume_agent(client, payload.user.id, channel_id, thread_ts, commands)


def _extract_interaction_context(
    payload: SlackInteractionPayload,
) -> tuple[str | None, str | None, str | None]:
    """Extract channel_id, thread_ts, and message_ts from an interaction payload."""
    channel_id = (
        payload.channel.id if payload.channel
        else payload.container.channel_id if payload.container
        else None
    )
    thread_ts = payload.container.thread_ts if payload.container else None
    message_ts = payload.container.message_ts if payload.container else None
    return channel_id, thread_ts, message_ts


async def _fetch_and_resolve_decisions(
    client: AsyncWebClient, channel_id: str, thread_ts: str,
) -> list[str] | None:
    """Fetch thread replies and return decisions if the latest batch is complete."""
    result = await client.conversations_replies(
        channel=channel_id, ts=thread_ts,
    )
    thread_messages = result.get("messages", [])
    return _collect_batch_decisions(thread_messages)


async def _resume_agent(
    client: AsyncWebClient,
    slack_user_id: str,
    channel_id: str,
    thread_ts: str,
    commands: list[str],
) -> None:
    """Look up the thread, build the agent runtime, and resume with *commands*."""
    user = await resolve_user(slack_user_id)
    if not user:
        return

    db = AsyncSessionLocal()
    thread = await db.get(ThreadDB, thread_ts)
    if not thread:
        await db.close()
        return

    await client.assistant_threads_setStatus(
        channel_id=channel_id, thread_ts=thread_ts, status="is typing...",
    )

    deps = build_agent_deps(thread, db)
    agent_runtime = await AgentRuntime.create(thread=thread, db=db, deps=deps)

    streamer = await client.chat_stream(
        channel=channel_id,
        thread_ts=thread_ts,
        recipient_user_id=slack_user_id,
    )

    approval_requests = await _stream_and_collect_approvals(
        agent_runtime, streamer, commands=commands,
    )

    for req in approval_requests:
        await post_tool_approval_block(client, channel_id, thread_ts, req)
