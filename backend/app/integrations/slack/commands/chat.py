"""Slack agent picker — lets users pick an agent for the current thread."""

from uuid import UUID

from slack_sdk.web.async_client import AsyncWebClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.core.service import AgentService
from app.agents.models import AgentDB
from app.agents.schemas import AgentResponse
from app.database import AsyncSessionLocal
from app.integrations.slack.models import SlackInteractionPayload
from app.integrations.slack.settings import slack_settings
from app.integrations.slack.utils import get_user_info
from app.threads.service import ThreadService
from app.users.models import WorkspaceRole
from app.users.repository import UserRepository


# Slack caps an `actions` block at 25 elements, so each page shows at most 24
# agent buttons and keeps the 25th slot free for the "Show more" button.
PAGE_SIZE = 24

DEFAULT_PICKER_HEADER = "Choose an agent for this thread:"


# ---------------------------------------------------------------------------
# Agent fetching
# ---------------------------------------------------------------------------

async def list_pickable_agents(
    db: AsyncSession, user_id: UUID, user_role: WorkspaceRole | None = None,
) -> list[AgentResponse]:
    """Return the agents this user may pick, in a stable, paginated order.

    Sorting by (name, id) keeps the order identical across the initial render
    and every subsequent "Show more" click, so pagination stays consistent.
    """
    all_agents = await AgentService(db).list(user_id=user_id, user_role=user_role)
    agents = [a for a in all_agents if a.current_user_permission is not None]
    agents.sort(key=lambda a: ((a.name or "").lower(), str(a.id)))
    return agents


# ---------------------------------------------------------------------------
# Block Kit builders
# ---------------------------------------------------------------------------

def _agent_button(agent: AgentResponse) -> dict:
    return {
        "type": "button",
        "text": {"type": "plain_text", "text": f"{agent.emoji or ''} {agent.name}".strip()},
        "action_id": f"select_agent:{agent.id}",
        "value": str(agent.id),
    }


def build_agent_picker_blocks(
    agents: list[AgentResponse],
    *,
    shown: int = PAGE_SIZE,
    header_text: str = DEFAULT_PICKER_HEADER,
) -> list[dict]:
    """Build the agent picker, revealing the first ``shown`` agents.

    Agent buttons are chunked into ``actions`` blocks of ``PAGE_SIZE`` (Slack
    caps each block at 25 elements). When more agents remain, a trailing
    "Show more" button reveals the next ``PAGE_SIZE`` via the
    ``load_more_agents:<count>`` action — each click accumulates onto the
    agents already shown rather than replacing them.
    """
    visible = agents[:shown]
    blocks: list[dict] = [
        {"type": "section", "text": {"type": "mrkdwn", "text": header_text}},
    ]
    for start in range(0, len(visible), PAGE_SIZE):
        batch = visible[start:start + PAGE_SIZE]
        blocks.append({"type": "actions", "elements": [_agent_button(a) for a in batch]})

    if shown < len(agents):
        next_shown = min(shown + PAGE_SIZE, len(agents))
        remaining = len(agents) - shown
        blocks.append({
            "type": "actions",
            "elements": [{
                "type": "button",
                "text": {"type": "plain_text", "text": f"➕ Show {remaining} more"},
                "action_id": f"load_more_agents:{next_shown}",
                "value": str(next_shown),
            }],
        })
    return blocks


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
    client: AsyncWebClient, channel_id: str, thread_ts: str,
    db: AsyncSession, user_id: UUID, user_role: WorkspaceRole | None = None,
) -> None:
    """Post an agent picker in the thread."""
    agents = await list_pickable_agents(db, user_id, user_role)
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
# Interaction handler (agent button click)
# ---------------------------------------------------------------------------

async def handle_agent_selection(payload: SlackInteractionPayload) -> None:
    """Process an agent-selection button click.

    Creates (or retrieves) the thread and replaces the picker message
    with a confirmation showing the chosen agent.
    """
    action = payload.actions[0]
    agent_id = action.value

    if not action.action_id.startswith("select_agent:"):
        return

    channel_id = (
        payload.channel.id if payload.channel
        else payload.container.channel_id if payload.container
        else None
    )
    thread_ts = payload.container.thread_ts if payload.container else None
    message_ts = payload.container.message_ts if payload.container else None
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

    # Fetch the agent
    async with AsyncSessionLocal() as db:
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
            channel=channel_id, ts=message_ts,
            blocks=blocks, text=f"{agent.emoji or ''} *{agent.name}*\n\nAsk me anything to begin.",
        )


# ---------------------------------------------------------------------------
# Interaction handler ("Show more" button click)
# ---------------------------------------------------------------------------

def _extract_header_text(payload: SlackInteractionPayload) -> str | None:
    """Recover the picker's original header so re-renders keep the same greeting."""
    blocks = payload.message.blocks if payload.message else []
    for block in blocks:
        if block.get("type") == "section":
            text = block.get("text")
            if isinstance(text, dict):
                return text.get("text")
    return None


async def handle_load_more_agents(payload: SlackInteractionPayload) -> None:
    """Reveal the next page of agents in-place when "Show more" is clicked.

    Re-fetches the (permission-scoped, stably ordered) agent list and rebuilds
    the picker showing the first ``shown`` agents — the count encoded in the
    button — then updates the message so previously shown agents stay visible.
    """
    action = payload.actions[0]
    if not action.action_id.startswith("load_more_agents:"):
        return

    try:
        shown = int(action.value)
    except (TypeError, ValueError):
        return

    channel_id = (
        payload.channel.id if payload.channel
        else payload.container.channel_id if payload.container
        else None
    )
    message_ts = payload.container.message_ts if payload.container else None
    if not channel_id or not message_ts:
        return

    # Resolve Slack user → internal user (the agent list is permission-scoped)
    user_info = await get_user_info(payload.user.id)
    if not user_info or not user_info.profile.email:
        return
    async with AsyncSessionLocal() as db:
        user = await UserRepository(db).get_by_email(user_info.profile.email)
    if not user:
        return

    async with AsyncSessionLocal() as db:
        agents = await list_pickable_agents(db, user.id, user.role)
    if not agents:
        return

    header_text = _extract_header_text(payload) or DEFAULT_PICKER_HEADER
    blocks = build_agent_picker_blocks(agents, shown=shown, header_text=header_text)

    client = AsyncWebClient(token=slack_settings.slack_bot_token)
    await client.chat_update(
        channel=channel_id, ts=message_ts, blocks=blocks, text="Choose an agent",
    )
