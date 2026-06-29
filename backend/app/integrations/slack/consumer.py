"""Worker-side Slack delivery for durable runs.

A Slack turn has no client connection to ride the event log, so the worker spawns
a `SlackRunConsumer`: it subscribes to the run's SSE event log, relays text and
tool labels into a Slack streaming message (`chat.startStream`/`appendStream`/
`stopStream` via `slack_sdk`'s `chat_stream`), and on the terminal event posts
either the tool-approval blocks (interrupted) or the "View in auxilia" link
(success). This is the Slack half of the durable runtime — the web tier only
enqueues the run (see `router.py`).
"""

import logging

from redis.asyncio import Redis
from slack_sdk.web.async_client import AsyncWebClient

from app.agents.runs.delivery import DeliveryConsumer
from app.agents.runs.service import RunService
from app.agents.runs.state import RunRecord, RunStatus
from app.agents.stream import SlackStreamAdapter
from app.auth.settings import auth_settings
from app.database import AsyncSessionLocal, get_checkpointer
from app.integrations.slack.blocks import (
    build_tool_approval_blocks,
    format_tool_streamer_label,
)
from app.integrations.slack.settings import slack_settings
from app.threads.models import ThreadDB
from app.threads.serialization import pending_approval_requests


logger = logging.getLogger(__name__)

SLACK_CHANNEL = "slack"

# Terminal statuses that didn't produce a clean answer. The agent may emit no
# `error` SSE at all (an exception in build/stream finalizes the run as `error`
# without publishing one), so the consumer must surface these itself or the
# Slack thread goes silent.
_FAILURE_STATUSES = frozenset({RunStatus.error.value, RunStatus.timeout.value})
_FAILURE_NOTICE = "\n\n⚠️ _Something went wrong while generating a response._"


def build_slack_run_consumer(record: RunRecord) -> "SlackRunConsumer | None":
    """The `DeliveryFactory` for Slack: build a consumer iff the run is Slack-bound."""
    delivery = record.delivery
    if not delivery or delivery.get("channel") != SLACK_CHANNEL:
        return None
    return SlackRunConsumer(record)


def build_slack_delivery(
    *, channel_id: str, thread_ts: str, slack_user_id: str, team_id: str | None
) -> dict:
    """The opaque delivery descriptor stored on a Slack-bound run."""
    return {
        "channel": SLACK_CHANNEL,
        "channel_id": channel_id,
        "thread_ts": thread_ts,
        "slack_user_id": slack_user_id,
        "team_id": team_id,
    }


class SlackRunConsumer(DeliveryConsumer):
    """Relays one run's event log to its Slack thread."""

    def __init__(self, record: RunRecord, redis: Redis | None = None):
        self.record = record
        self.delivery = record.delivery or {}
        self.redis = redis
        self.client = AsyncWebClient(token=slack_settings.slack_bot_token)

    async def run(self) -> None:
        channel_id = self.delivery["channel_id"]
        thread_ts = self.delivery["thread_ts"]

        streamer = await self.client.chat_stream(
            channel=channel_id,
            thread_ts=thread_ts,
            recipient_team_id=self.delivery.get("team_id"),
            recipient_user_id=self.delivery.get("slack_user_id"),
        )
        adapter = SlackStreamAdapter()
        status: str | None = None
        # Always close the streaming message: a transient Redis/SSE or Slack
        # append error must not leave an in-progress Slack message open, even
        # though the worker treats delivery as best-effort.
        try:
            async for event in adapter.stream(
                RunService(self.redis).stream(self.record.id)
            ):
                kind = event["type"]
                if kind == "text":
                    await streamer.append(markdown_text=event["content"])
                elif kind == "tool_start":
                    await streamer.append(
                        markdown_text=format_tool_streamer_label(event["tool_name"])
                    )
                elif kind == "error":
                    await streamer.append(
                        markdown_text=f"**`Error: {event['content']}`**\n\n"
                    )
                elif kind == "end":
                    status = event["status"]
                    if status in _FAILURE_STATUSES:
                        # Append before the stream is finalized in `finally`.
                        await streamer.append(markdown_text=_FAILURE_NOTICE)
        finally:
            await streamer.stop()

        if status == RunStatus.interrupted.value:
            await self._post_approvals(channel_id, thread_ts)
        elif status == RunStatus.success.value:
            await self._post_auxilia_link(channel_id, thread_ts)

    async def _post_approvals(self, channel_id: str, thread_ts: str) -> None:
        """Post a Block Kit approve/reject message per pending tool call."""
        async with get_checkpointer() as checkpointer:
            checkpoint = await checkpointer.aget_tuple(
                config={"configurable": {"thread_id": self.record.thread_id}}
            )
        for request in pending_approval_requests(checkpoint):
            blocks = build_tool_approval_blocks(
                request["tool_call_id"], request["tool_name"], request["input"]
            )
            await self.client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                blocks=blocks,
                text=f"Approve {request['tool_name']}?",
            )

    async def _post_auxilia_link(self, channel_id: str, thread_ts: str) -> None:
        """Post a divider + 'View in auxilia' link once the turn finishes cleanly."""
        async with AsyncSessionLocal() as db:
            thread = await db.get(ThreadDB, self.record.thread_id)
        if thread is None:
            return
        url = f"{auth_settings.FRONTEND_URL}/agents/{thread.agent_id}/chat/{thread.id}"
        await self.client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            blocks=[
                {"type": "divider"},
                {
                    "type": "context",
                    "elements": [
                        {"type": "mrkdwn", "text": f"<{url}|*View in auxilia*>"}
                    ],
                },
            ],
        )
