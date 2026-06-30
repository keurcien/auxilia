# Handlers contain the business logic for each Slack event type.
#
# Threads are created when the user picks an agent via the agent picker
# (triggered by @auxilia mention). Subsequent messages in that thread are
# routed to the configured agent by *enqueuing a durable run* — the web tier
# never executes the agent itself (see `app/agents/runs/` and `consumer.py`).

import logging

from slack_sdk.web.async_client import AsyncWebClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.agents.core.service import AgentService
from app.agents.runs.service import RunService
from app.auth.settings import auth_settings
from app.database import AsyncSessionLocal
from app.exceptions import DomainValidationError
from app.integrations.slack.commands.chat import (
    build_agent_picker_blocks,
    list_pickable_agents,
    post_agent_picker,
)
from app.integrations.slack.consumer import build_slack_delivery
from app.integrations.slack.models import SlackEvent, SlackInteractionPayload
from app.integrations.slack.settings import slack_settings
from app.integrations.slack.utils import get_user_info, resolve_user
from app.mcp.servers.models import MCPServerDB
from app.mcp.utils import probe_mcp_server
from app.threads.models import ThreadDB
from app.users.repository import UserRepository


logger = logging.getLogger(__name__)


async def _enqueue_slack_run(
    *,
    thread_id: str,
    user_id: str,
    channel_id: str,
    slack_user_id: str,
    team_id: str | None,
    input: dict | None = None,
    command: dict | None = None,
) -> None:
    """Create a durable run for a Slack turn; the worker executes + delivers it.

    A duplicate that slips the webhook dedup races the per-thread mutex and is
    rejected at create time — swallowed here so Slack still gets a clean ack.
    """
    delivery = build_slack_delivery(
        channel_id=channel_id,
        thread_ts=thread_id,
        slack_user_id=slack_user_id,
        team_id=team_id,
    )
    try:
        await RunService().create(
            thread_id=thread_id,
            user_id=user_id,
            input=input,
            command=command,
            delivery=delivery,
        )
    except DomainValidationError:
        logger.info("Slack run for thread %s skipped: active run exists", thread_id)


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
    """Extract the decision from a decided approval message.

    The decision lives in the `context` block that `_update_approval_message`
    swaps in for the buttons; that block is the only one carrying the status emoji.
    """
    for block in msg.get("blocks", []):
        if block.get("type") != "context":
            continue
        text = " ".join(el.get("text", "") for el in block.get("elements", []))
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

    commands = [d for msg in batch if (d := _extract_decision(msg)) is not None]
    return commands or None


async def _update_approval_message(
    client: AsyncWebClient,
    channel_id: str,
    message_ts: str,
    blocks: list[dict],
    approved: bool,
) -> None:
    """Record the decision: drop the buttons and append a status context block.

    The card no longer carries a tool-name header (the streamed label above it
    already shows it), so the decision marker lives in its own `context` block.
    That block is load-bearing, not cosmetic: the stateless batch-resume logic
    (`_extract_decision`) recovers each card's decision by reading this emoji
    back from the thread.
    """
    status_emoji = ":white_check_mark:" if approved else ":no_entry_sign:"
    status_label = "Approved" if approved else "Rejected"

    marker = {
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": f"{status_emoji} {status_label}"}],
    }
    # Replace the Approve/Reject buttons in place with the decision marker, so it
    # sits where the buttons were (above the trailing divider). A card that's
    # already decided has no actions block to replace, so it's left untouched.
    updated_blocks = [marker if b.get("type") == "actions" else b for b in blocks]

    await client.chat_update(
        channel=channel_id,
        ts=message_ts,
        blocks=updated_blocks,
        text=status_label,
    )


# ---------------------------------------------------------------------------
# Top-level event handlers
# ---------------------------------------------------------------------------


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
        channel_id=channel_id,
        thread_ts=thread_ts,
        status="is typing...",
    )

    user_info = await get_user_info(slack_user_id)
    display_name = (user_info.real_name or user_info.name) if user_info else "there"

    # Resolve Slack identity → internal user
    user = None
    if user_info and user_info.profile.email:
        async with AsyncSessionLocal() as db:
            user = await UserRepository(db).get_by_email(user_info.profile.email)

    if not user:
        await client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=f"Hi {display_name}! It seems like you haven't registered on auxilia yet.",
        )
        return

    async with AsyncSessionLocal() as db:
        agents = await list_pickable_agents(db, user.id, user.role, user.team_id)

    if not agents:
        await client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=f"Hi {display_name}! You don't have any agents configured yet.",
        )
        return

    blocks = build_agent_picker_blocks(
        agents,
        header_text=f"Hi {display_name}! Select an agent to begin a conversation:",
    )
    await client.chat_postMessage(
        channel=channel_id,
        thread_ts=thread_ts,
        blocks=blocks,
        text=f"Hi {display_name}! Select an agent to begin a conversation.",
    )


async def _is_agent_ready(agent_id: str, user_id: str, db: AsyncSession) -> bool:
    """Mirror the /is-ready endpoint: return True only when all bound MCP servers
    are connected for this user."""
    from uuid import UUID

    agent = await AgentService(db).get(UUID(agent_id))

    if not agent.mcp_servers:
        return True

    for mcp_server in agent.mcp_servers:
        if mcp_server.tools is None:
            return False

    server_ids = [s.id for s in agent.mcp_servers]
    result = await db.execute(select(MCPServerDB).where(MCPServerDB.id.in_(server_ids)))
    servers = result.scalars().all()

    for server in servers:
        if not await probe_mcp_server(server, user_id):
            return False

    return True


async def handle_message(event: SlackEvent, *, team_id: str | None = None) -> None:
    """Route a Slack message to the configured agent by enqueuing a durable run."""
    thread_ts = event.thread_ts or event.ts

    question = (event.text or "").strip()
    if not question:
        return

    user = await resolve_user(event.user)

    if not user:
        return

    client = AsyncWebClient(token=slack_settings.slack_bot_token)

    # Look up the existing thread (created when the user picked an agent)
    async with AsyncSessionLocal() as db:
        thread = await db.get(ThreadDB, thread_ts)

        if not thread:
            await post_agent_picker(
                client,
                event.channel,
                thread_ts,
                db,
                user.id,
                user_role=user.role,
                user_team_id=user.team_id,
            )
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
                                "text": {
                                    "type": "plain_text",
                                    "text": "Connect on auxilia",
                                },
                                "url": connect_url,
                                "style": "primary",
                            }
                        ],
                    },
                ],
            )
            return

        await client.assistant_threads_setStatus(
            channel_id=event.channel,
            thread_ts=thread_ts,
            status="is typing...",
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

    await _enqueue_slack_run(
        thread_id=thread_ts,
        user_id=str(user.id),
        channel_id=event.channel,
        slack_user_id=event.user,
        team_id=team_id,
        input={"messages": [{"type": "human", "content": question}]},
    )


async def handle_interaction(payload: SlackInteractionPayload) -> None:
    """Handle a Slack block_actions interaction (Approve/Reject buttons).

    Uses ``conversations.replies`` to derive approval state from the thread
    itself — no external state store needed. The agent is resumed (via a new
    durable run) only once every pending tool call has been decided.
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
            client,
            channel_id,
            message_ts,
            original_blocks,
            approved,
        )

    # Check whether the latest batch of approvals is fully decided
    commands = await _fetch_and_resolve_decisions(client, channel_id, thread_ts)
    if commands is None:
        return

    # All decided — resume the agent via a new run
    await _resume_agent(client, payload, channel_id, thread_ts, commands)


def _extract_interaction_context(
    payload: SlackInteractionPayload,
) -> tuple[str | None, str | None, str | None]:
    """Extract channel_id, thread_ts, and message_ts from an interaction payload."""
    channel_id = (
        payload.channel.id
        if payload.channel
        else payload.container.channel_id
        if payload.container
        else None
    )
    thread_ts = payload.container.thread_ts if payload.container else None
    message_ts = payload.container.message_ts if payload.container else None
    return channel_id, thread_ts, message_ts


async def _fetch_and_resolve_decisions(
    client: AsyncWebClient,
    channel_id: str,
    thread_ts: str,
) -> list[str] | None:
    """Fetch thread replies and return decisions if the latest batch is complete."""
    result = await client.conversations_replies(
        channel=channel_id,
        ts=thread_ts,
    )
    thread_messages = result.get("messages", [])
    return _collect_batch_decisions(thread_messages)


async def _resume_agent(
    client: AsyncWebClient,
    payload: SlackInteractionPayload,
    channel_id: str,
    thread_ts: str,
    commands: list[str],
) -> None:
    """Look up the thread and enqueue a HITL-resume run with *commands*."""
    user = await resolve_user(payload.user.id)
    if not user:
        return

    async with AsyncSessionLocal() as db:
        thread = await db.get(ThreadDB, thread_ts)
    if not thread:
        return

    await client.assistant_threads_setStatus(
        channel_id=channel_id,
        thread_ts=thread_ts,
        status="is typing...",
    )

    await _enqueue_slack_run(
        thread_id=thread_ts,
        user_id=str(user.id),
        channel_id=channel_id,
        slack_user_id=payload.user.id,
        team_id=(payload.team or {}).get("id"),
        command={"resume": {"decisions": [{"type": cmd} for cmd in commands]}},
    )
