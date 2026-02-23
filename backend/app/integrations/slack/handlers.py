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
from sqlmodel import select
from app.agents.utils import read_agent, read_agents
from app.mcp.servers.models import MCPServerDB
from app.mcp.utils import check_mcp_server_connected
from app.auth.settings import auth_settings
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
        elif ev["type"] == "tool_start":
            tool_name = ev["tool_name"]
            await streamer.append(markdown_text=f"\n\n:{tool_name.split('_')[0].lower()}:  **{tool_name.split('_')[0]}**  ›  `{'_'.join(tool_name.split('_')[1:])}`\n\n")
        elif ev["type"] == "tool_approval_request":
            approval_requests.append(ev)
        elif ev["type"] == "error":
            await streamer.append(markdown_text=f"**`Error: {ev['content']}`**\n\n")

    await streamer.stop()
    return approval_requests


async def _post_auxilia_link(
    client: AsyncWebClient, channel: str, thread_ts: str, thread: ThreadDB,
) -> None:
    """Post a divider + 'Open in auxilia' link as a Block Kit message."""
    url = f"{auth_settings.FRONTEND_URL}/agents/{thread.agent_id}/chat/{thread.id}"
    await client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        blocks=[
            {"type": "divider"},
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": f"<{url}|*View in auxilia*>"}],
            },
        ],
    )


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

    if not approval_requests:
        await _post_auxilia_link(client, event.channel, thread_ts, thread)


async def handle_assistant_thread_started(event: SlackEvent) -> None:
    """Welcome a user when they open a new AI-assistant thread.

    Sets a typing status, resolves the Slack identity to an internal account,
    then either explains the problem or presents the agent picker.
    """
    at = event.assistant_thread
    if not at or not at.user_id or not at.channel_id or not at.thread_ts:
        return

    channel_id = at.channel_id
    thread_ts = at.thread_ts
    slack_user_id = at.user_id

    client = AsyncWebClient(token=slack_settings.slack_bot_token)
    await client.assistant_threads_setStatus(
        channel_id=channel_id, thread_ts=thread_ts, status="is typing...",
    )

    user_info = await get_user_info(slack_user_id)
    display_name = (
        user_info.real_name or user_info.name) if user_info else "there"

    # Resolve Slack identity → internal user
    user = None
    if user_info and user_info.profile.email:
        async with AsyncSessionLocal() as db:
            user = await get_user_by_email(user_info.profile.email, db)

    if not user:
        await client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=f"Hi {display_name}! It seems like you haven't registered on auxilia yet.",
        )
        return

    async with AsyncSessionLocal() as db:
        all_agents = await read_agents(db, user_id=user.id, user_role=user.role)
    agents = [a for a in all_agents if a.current_user_permission is not None]

    if not agents:
        await client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=f"Hi {display_name}! You don't have any agents configured yet.",
        )
        return

    buttons = [
        {
            "type": "button",
            "text": {"type": "plain_text", "text": f"{a.emoji or ''} {a.name}".strip()},
            "action_id": f"select_agent:{a.id}",
            "value": str(a.id),
        }
        for a in agents
    ]
    await client.chat_postMessage(
        channel=channel_id,
        thread_ts=thread_ts,
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"Hi {display_name}! Select an agent to begin a conversation:",
                },
            },
            {"type": "actions", "elements": buttons},
        ],
        text=f"Hi {display_name}! Select an agent to begin a conversation.",
    )


async def _is_agent_ready(agent_id: str, user_id: str, db: AsyncSession) -> bool:
    """Mirror the /is-ready endpoint: return True only when all bound MCP servers
    are connected for this user."""
    from uuid import UUID
    agent = await read_agent(UUID(agent_id), db)

    if not agent.mcp_servers:
        return True

    for mcp_server in agent.mcp_servers:
        if mcp_server.tools is None:
            return False

    server_ids = [s.id for s in agent.mcp_servers]
    result = await db.execute(select(MCPServerDB).where(MCPServerDB.id.in_(server_ids)))
    servers = result.scalars().all()

    for server in servers:
        if not await check_mcp_server_connected(server, user_id):
            return False

    return True


async def handle_message(event: SlackEvent, *, team_id: str | None = None) -> None:
    """Route a Slack message to the configured agent for this thread."""
    thread_ts = event.thread_ts or event.ts

    question = (event.text or "").strip()
    if not question:
        return

    user = await resolve_user(event.user)

    if not user:
        return

    client = AsyncWebClient(token=slack_settings.slack_bot_token)

    # Look up the existing thread (created when the user picked an agent)
    db = AsyncSessionLocal()
    try:
        thread = await db.get(ThreadDB, thread_ts)

        if not thread:
            await post_agent_picker(client, event.channel, thread_ts, db, user.id, user_role=user.role)
            return

        if not await _is_agent_ready(str(thread.agent_id), str(user.id), db):
            connect_url = f"{auth_settings.FRONTEND_URL}/agents/{thread.agent_id}/chat"
            await client.chat_postMessage(
                channel=event.channel,
                thread_ts=thread_ts,
                blocks=[
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
                ],
            )
            return

        await client.assistant_threads_setStatus(
            channel_id=event.channel, thread_ts=thread_ts, status="is typing...",
        )

        # Set the Slack thread title to the first real user message.
        if not thread.first_message_content:
            thread.first_message_content = question
            await db.commit()
            await client.assistant_threads_setTitle(
                channel_id=event.channel,
                thread_ts=thread_ts,
                title=question[:255],
            )

        await stream_agent_response(
            thread, db, question, event, client, team_id=team_id,
        )
    finally:
        await db.close()


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
    try:
        thread = await db.get(ThreadDB, thread_ts)
        if not thread:
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

        if not approval_requests:
            await _post_auxilia_link(client, channel_id, thread_ts, thread)
    finally:
        await db.close()
