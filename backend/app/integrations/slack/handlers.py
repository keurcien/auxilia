# Handlers contain the business logic for each Slack event type.
#
# Right now we only handle "message" events and stream back a lorem
# ipsum text using Slack's chat streaming API (chat.startStream,
# chat.appendStream, chat.stopStream).  When agent invocation is
# wired in, the lorem ipsum chunks would be replaced by LLM output.

import asyncio
import uuid
import httpx
from slack_sdk.web.async_client import AsyncWebClient
from langchain.messages import HumanMessage
from app.integrations.slack.models import SlackEvent
from app.integrations.slack.settings import slack_settings
from app.integrations.slack.utils import get_user_info
from app.users.service import get_user_by_email
from app.database import AsyncSessionLocal
from app.agents.runtime import AgentRuntime, AgentRuntimeDependencies, ChatModelFactory, MCPClientConfigFactory
from app.mcp.servers.router import get_mcp_server_api_key
from app.mcp.client.storage import TokenStorageFactory
from app.threads.models import ThreadDB


SLACK_POST_MESSAGE_URL = "https://slack.com/api/chat.postMessage"


async def notify_user_not_found(event: SlackEvent) -> None:
    """Notify the user that they are not found."""
    async with httpx.AsyncClient() as client:
        await client.post(
            SLACK_POST_MESSAGE_URL,
            headers={"Authorization": f"Bearer {slack_settings.slack_bot_token}"},
            json={"channel": event.channel, "text": "User not found.",
                  "thread_ts": event.thread_ts or event.ts},
        )


async def handle_message(event: SlackEvent, *, team_id: str | None = None) -> None:
    """Stream a lorem ipsum response back to the Slack channel."""

    slack_user_id = event.user
    thread_ts = event.thread_ts or event.ts

    user_info = await get_user_info(slack_user_id)

    user = None

    if user_info and user_info.profile.email:
        async with AsyncSessionLocal() as db:
            user = await get_user_by_email(user_info.profile.email, db)

    if not user:
        await notify_user_not_found(event)
        return

    client = AsyncWebClient(token=slack_settings.slack_bot_token)

    # Determine if this is a parent message or thread reply
    # Parent message: thread_ts is not present in the event
    # Thread reply: thread_ts is present and different from ts
    is_parent_message = event.thread_ts is None

    await client.assistant_threads_setStatus(
        channel_id=event.channel,
        thread_ts=thread_ts,
        status="is typing...",
    )

    thread = ThreadDB(
        id=uuid.uuid4(),
        agent_id="6533e2e9-43cc-4f47-abfe-b58c7c013610",
        model_id="deepseek-chat",
        first_message_content=event.text,
        user_id=user.id
    )

    # Create thread
    # TODO Add thread services
    async with AsyncSessionLocal() as db:
        db.add(thread)
        await db.commit()
        await db.refresh(thread)

    streamer = await client.chat_stream(
        channel=event.channel,
        thread_ts=thread_ts,
        recipient_team_id=team_id,
        recipient_user_id=event.user,
    )

    deps = AgentRuntimeDependencies(
        model_factory=ChatModelFactory(),
        mcp_client_config_factory=MCPClientConfigFactory(
            resolve_api_key=lambda mcp_server_config: get_mcp_server_api_key(
                mcp_server_config.id, db),
            resolve_storage=lambda mcp_server_config: TokenStorageFactory(
            ).get_storage(thread.user_id, mcp_server_config.id),
        )
    )
    agent_runtime = await AgentRuntime.create(thread=thread, db=db, deps=deps)

    async for chunk in agent_runtime.stream(messages=[HumanMessage(content=event.text)], stream_adapter="slack"):
        await streamer.append(markdown_text=chunk)

    await streamer.stop()
