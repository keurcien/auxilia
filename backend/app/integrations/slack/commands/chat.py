"""Slack agent picker — lets users pick an agent for the current thread."""

import asyncio
import logging
from uuid import UUID

from slack_sdk.web.async_client import AsyncWebClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.core.service import AgentService
from app.agents.models import AgentDB
from app.agents.schemas import AgentListResponse
from app.database import AsyncSessionLocal
from app.integrations.slack.models import SlackInteractionPayload
from app.integrations.slack.settings import slack_settings
from app.integrations.slack.utils import get_user_info, resolve_user
from app.threads.service import ThreadService
from app.users.models import WorkspaceRole
from app.users.repository import UserRepository


# Slack caps each external-select search response at 100 options.
MAX_OPTIONS = 100
OPTIONS_TIMEOUT_SECONDS = 2.5
logger = logging.getLogger(__name__)

DEFAULT_PICKER_HEADER = "Choose an agent for this thread:"
SELECT_AGENT_ACTION_ID = "select_agent"


# ---------------------------------------------------------------------------
# Agent fetching
# ---------------------------------------------------------------------------


async def list_pickable_agents(
    db: AsyncSession,
    user_id: UUID,
    user_role: WorkspaceRole | None = None,
    user_team_id: UUID | None = None,
) -> list[AgentListResponse]:
    """Return the agents this user may pick, sorted by name."""
    all_agents = await AgentService(db).list(
        user_id=user_id, user_role=user_role, user_team_id=user_team_id
    )
    agents = [a for a in all_agents if a.current_user_permission is not None]
    agents.sort(key=lambda a: ((a.name or "").lower(), str(a.id)))
    return agents


# ---------------------------------------------------------------------------
# Block Kit builders
# ---------------------------------------------------------------------------


def _agent_option(agent: AgentListResponse) -> dict:
    return {
        "text": {
            "type": "plain_text",
            "text": f"{agent.emoji or ''} {agent.name}".strip()[:75],
        },
        "value": str(agent.id),
    }


def build_agent_picker_blocks(
    _agents: list[AgentListResponse],
    *,
    header_text: str = DEFAULT_PICKER_HEADER,
) -> list[dict]:
    """Use server-side search so every accessible agent can be selected."""
    return [
        {"type": "section", "text": {"type": "mrkdwn", "text": header_text}},
        {
            "type": "actions",
            "elements": [
                {
                    "type": "external_select",
                    "action_id": SELECT_AGENT_ACTION_ID,
                    "placeholder": {
                        "type": "plain_text",
                        "text": "Search agents by name or ID…",
                    },
                    "min_query_length": 0,
                }
            ],
        },
    ]


def search_agent_options(agents: list[AgentListResponse], query: str) -> list[dict]:
    """Filter before limiting; exact names precede prefixes and substrings."""
    query = query.strip().casefold()
    matches = [
        a for a in agents if query in (a.name or "").casefold() or query == str(a.id)
    ]
    matches.sort(
        key=lambda a: (
            0
            if query in ((a.name or "").casefold(), str(a.id))
            else 1
            if (a.name or "").casefold().startswith(query)
            else 2,
            (a.name or "").casefold(),
            str(a.id),
        )
    )
    return [_agent_option(a) for a in matches[:MAX_OPTIONS]]


async def handle_agent_options(payload: SlackInteractionPayload) -> dict:
    if payload.action_id != SELECT_AGENT_ACTION_ID:
        return {"options": []}
    try:
        # Includes cache misses and database work; leave time for HTTP serialization.
        async with asyncio.timeout(OPTIONS_TIMEOUT_SECONDS):
            user = await resolve_user(payload.user.id)
            if not user:
                return {"options": []}
            async with AsyncSessionLocal() as db:
                agents = await list_pickable_agents(
                    db, user.id, user.role, user.team_id
                )
            return {"options": search_agent_options(agents, payload.value or "")}
    except TimeoutError:
        logger.warning("Slack agent options timed out")
        return {"options": []}


def _build_agent_selected_blocks(agent: AgentDB) -> list[dict]:
    """Build Block Kit blocks confirming the selected agent."""
    emoji = agent.emoji or ":robot_face:"
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"{emoji} *{agent.name}*\n\nAsk me anything to begin.",
            },
        },
    ]


# ---------------------------------------------------------------------------
# Post agent picker
# ---------------------------------------------------------------------------


async def post_agent_picker(
    client: AsyncWebClient,
    channel_id: str,
    thread_ts: str,
    db: AsyncSession,
    user_id: UUID,
    user_role: WorkspaceRole | None = None,
    user_team_id: UUID | None = None,
) -> None:
    """Post an agent picker in the thread."""
    agents = await list_pickable_agents(db, user_id, user_role, user_team_id)
    if not agents:
        return

    blocks = build_agent_picker_blocks(agents)
    await client.chat_postMessage(
        channel=channel_id,
        thread_ts=thread_ts,
        blocks=blocks,
        text="Choose an agent",
    )


# ---------------------------------------------------------------------------
# Interaction handler (dropdown selection)
# ---------------------------------------------------------------------------


async def handle_agent_selection(payload: SlackInteractionPayload) -> None:
    """Process an agent-selection dropdown choice.

    Creates (or retrieves) the thread and replaces the picker message
    with a confirmation showing the chosen agent.
    """
    action = payload.actions[0]
    if action.action_id != SELECT_AGENT_ACTION_ID:
        return

    selected = action.selected_option
    if not selected:
        return
    agent_id = selected.value

    channel_id = (
        payload.channel.id
        if payload.channel
        else payload.container.channel_id
        if payload.container
        else None
    )
    thread_ts = (payload.container.thread_ts if payload.container else None) or (
        payload.message.thread_ts if payload.message else None
    )
    message_ts = (payload.container.message_ts if payload.container else None) or (
        payload.message.ts if payload.message else None
    )
    if not channel_id or not thread_ts:
        return

    # Resolve Slack user → internal user
    user_info = await get_user_info(payload.user.id)
    if not user_info or not user_info.profile.email:
        return
    async with AsyncSessionLocal() as db:
        user = await UserRepository(db).get_by_email(user_info.profile.email)
    if not user:
        return

    # Recheck access at selection time: suggestions can be stale or forged.
    async with AsyncSessionLocal() as db:
        allowed = await list_pickable_agents(db, user.id, user.role, user.team_id)
        if not any(str(a.id) == agent_id for a in allowed):
            return
        agent = await db.get(AgentDB, agent_id)
    if not agent:
        return

    # Create the thread bound to this agent.
    # first_message_content is left None here; it will be set (and the Slack
    # thread title updated) when the user sends their first real message.
    async with AsyncSessionLocal() as db:
        await ThreadService(db).get_or_create(
            ts=thread_ts,
            agent_id=str(agent.id),
            question=None,
            user_id=str(user.id),
        )
        await db.commit()

    # Replace the picker message with a confirmation
    client = AsyncWebClient(token=slack_settings.slack_bot_token)
    blocks = _build_agent_selected_blocks(agent)
    if message_ts:
        await client.chat_update(
            channel=channel_id,
            ts=message_ts,
            blocks=blocks,
            text=f"{agent.emoji or ''} *{agent.name}*\n\nAsk me anything to begin.",
        )
