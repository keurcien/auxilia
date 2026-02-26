"""Slack agent picker — lets users pick an agent for the current thread."""
from sqlalchemy.ext.asyncio import AsyncSession
from slack_sdk.web.async_client import AsyncWebClient

from app.agents.models import AgentDB
from app.agents.utils import read_agents
from app.integrations.slack.models import SlackEvent, SlackInteractionPayload
from app.integrations.slack.settings import slack_settings
from app.integrations.slack.utils import get_user_info, resolve_user
from app.threads.service import get_or_create_thread
from app.users.models import WorkspaceRole
from app.users.service import get_user_by_email
from app.database import AsyncSessionLocal


# ---------------------------------------------------------------------------
# Block Kit builders
# ---------------------------------------------------------------------------

def _build_agent_picker_blocks(agents: list[AgentDB]) -> list[dict]:
    """Build Block Kit blocks with one button per agent."""
    buttons = [
        {
            "type": "button",
            "text": {"type": "plain_text", "text": f"{agent.emoji or ''} {agent.name}".strip()},
            "action_id": f"select_agent:{agent.id}",
            "value": str(agent.id),
        }
        for agent in agents
    ]
    return [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "Choose an agent for this thread:"},
        },
        {
            "type": "actions",
            "elements": buttons,
        },
    ]


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
    db: AsyncSession, user_id: str, user_role: WorkspaceRole | None = None,
) -> None:
    """Post an agent picker in the thread."""
    all_agents = await read_agents(db, user_id=user_id, user_role=user_role)
    agents = [a for a in all_agents if a.current_user_permission is not None]
    if not agents:
        return

    blocks = _build_agent_picker_blocks(agents)
    await client.chat_postMessage(
        channel=channel_id,
        thread_ts=thread_ts,
        blocks=blocks,
        text="Choose an agent",
    )


async def handle_app_mention(event: SlackEvent, **_: object) -> None:
    """Handle an ``app_mention`` event — post an agent picker in the thread."""
    thread_ts = event.thread_ts or event.ts
    if not event.channel or not thread_ts:
        return

    user = await resolve_user(event.user)

    if not user:
        return

    async with AsyncSessionLocal() as db:
        client = AsyncWebClient(token=slack_settings.slack_bot_token)
        await post_agent_picker(
            client, event.channel, thread_ts, db, user.id, user_role=user.role,
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
        user = await get_user_by_email(user_info.profile.email, db)
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
    await get_or_create_thread(
        ts=thread_ts,
        agent_id=str(agent.id),
        question=None,
        user_id=str(user.id),
    )

    # Replace the picker message with a confirmation
    client = AsyncWebClient(token=slack_settings.slack_bot_token)
    blocks = _build_agent_selected_blocks(agent)
    if message_ts:
        await client.chat_update(
            channel=channel_id, ts=message_ts,
            blocks=blocks, text=f"{agent.emoji or ''} *{agent.name}*\n\nAsk me anything to begin.",
        )
