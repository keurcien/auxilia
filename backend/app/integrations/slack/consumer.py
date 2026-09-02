"""Worker-side Slack delivery for durable runs.

A Slack turn has no client connection to ride the event log, so the worker spawns
a `SlackRunConsumer`: it subscribes to the run's event log (Agent Streaming
Protocol events, see `app/agents/protocol/`), relays root text deltas and tool
labels into a Slack streaming message (`chat.startStream`/`appendStream`/
`stopStream` via `slack_sdk`'s `chat_stream`), and once the run is terminal
posts either the tool-approval blocks (interrupted) or the "View in auxilia"
link (success). This is the Slack half of the durable runtime — the web tier
only enqueues the run (see `router.py`).
"""

import logging
from typing import Any, Final, Literal, TypedDict, cast

from redis.asyncio import Redis
from slack_sdk.web.async_client import AsyncWebClient

from app.agents.hitl import pending_approval_requests, pending_interrupt
from app.agents.protocol.wire import decode_event
from app.agents.runs.delivery import DeliveryConsumer
from app.agents.runs.models import RunDB
from app.agents.runs.service import RunService
from app.agents.runs.state import MCP_REAUTH_ERROR, RunStatus, is_terminal
from app.auth.settings import auth_settings
from app.database import AsyncSessionLocal, get_checkpointer
from app.integrations.slack.blocks import (
    build_connect_prompt_blocks,
    build_tool_approval_blocks,
    format_tool_streamer_label,
)
from app.integrations.slack.settings import slack_settings
from app.threads.models import ThreadDB


logger = logging.getLogger(__name__)

# Final, so mypy sees Literal["slack"] and the SlackDelivery construction checks.
SLACK_CHANNEL: Final = "slack"


class SlackDelivery(TypedDict):
    """The delivery descriptor stored on a Slack-bound run (`RunDB.delivery`).

    Written by `build_slack_delivery`, read back as JSONB — the shape is a
    contract between the enqueue path and this consumer, so it is a TypedDict
    rather than an opaque dict: mistype a key on either side and mypy fails
    instead of a KeyError mid-delivery.
    """

    channel: Literal["slack"]
    channel_id: str
    thread_ts: str
    slack_user_id: str
    team_id: str | None


def build_slack_run_consumer(record: RunDB) -> "SlackRunConsumer | None":
    """The `DeliveryFactory` for Slack: build a consumer iff the run is Slack-bound."""
    delivery = record.delivery
    if not delivery or delivery.get("channel") != SLACK_CHANNEL:
        return None
    return SlackRunConsumer(record)


def build_slack_delivery(
    *, channel_id: str, thread_ts: str, slack_user_id: str, team_id: str | None
) -> SlackDelivery:
    """The delivery descriptor stored on a Slack-bound run."""
    return {
        "channel": SLACK_CHANNEL,
        "channel_id": channel_id,
        "thread_ts": thread_ts,
        "slack_user_id": slack_user_id,
        "team_id": team_id,
    }


class SlackProtocolAdapter:
    """Turns stored protocol events into what the Slack streamer appends.

    Only the **root** namespace is surfaced — subagent tokens stream under
    `tools:<task-id>` namespaces and are intentionally skipped, as before.
    `messages` text deltas are relayed only while the open message is
    AI-authored (a `message-start` with role `ai`): the tool-role message
    triple carries the raw tool result, and reasoning deltas are excluded.
    `tool-started` yields the tool label. Approval requests are *not* derived
    from `input.requested`: the HITL payload names tools without their
    tool-call ids, so the consumer reads them off the checkpoint
    (`pending_approval_requests`) once the run is terminal.
    """

    def __init__(self) -> None:
        self._tools_started: set[str] = set()
        # The role of the message currently open on the root namespace, per
        # node — deltas from a tool-role message must not reach the chat.
        self._open_role: dict[str, str] = {}

    def texts(self, event: dict[str, Any]) -> list[str]:
        """Markdown chunks to append for one protocol event (usually 0 or 1)."""
        params = event.get("params") or {}
        if params.get("namespace"):
            return []
        data = params.get("data")
        if not isinstance(data, dict):
            return []
        method = event.get("method")
        if method == "messages":
            return self._on_message(str(params.get("node") or ""), data)
        if method == "tools" and data.get("event") == "tool-started":
            tool_call_id = data.get("tool_call_id")
            tool_name = data.get("tool_name")
            if tool_call_id and tool_name and tool_call_id not in self._tools_started:
                self._tools_started.add(tool_call_id)
                return [format_tool_streamer_label(str(tool_name))]
        return []

    def _on_message(self, node: str, data: dict[str, Any]) -> list[str]:
        kind = data.get("event")
        if kind == "message-start":
            self._open_role[node] = str(data.get("role") or "ai")
            return []
        if kind == "message-finish":
            self._open_role.pop(node, None)
            return []
        if self._open_role.get(node, "ai") != "ai":
            return []
        if kind == "content-block-start":
            content = data.get("content")
            if isinstance(content, dict) and content.get("type") == "text":
                text = content.get("text")
                return [text] if isinstance(text, str) and text else []
        elif kind == "content-block-delta":
            delta = data.get("delta")
            if isinstance(delta, dict) and delta.get("type") == "text-delta":
                text = delta.get("text")
                return [text] if isinstance(text, str) and text else []
        return []


class SlackRunConsumer(DeliveryConsumer):
    """Relays one run's event log to its Slack thread."""

    def __init__(self, record: RunDB, redis: Redis | None = None):
        self.record = record
        # The factory only builds this consumer for a record whose delivery
        # carries channel == "slack", so the JSONB dict is a SlackDelivery.
        self.delivery = cast(SlackDelivery, record.delivery or {})
        self.redis = redis
        self.client = AsyncWebClient(token=slack_settings.slack_bot_token)

    async def run(self) -> None:
        channel_id = self.delivery["channel_id"]
        thread_ts = self.delivery["thread_ts"]
        logger.info(
            "Slack delivery starting for run %s (channel=%s, thread_ts=%s)",
            self.record.id,
            channel_id,
            thread_ts,
        )
        try:
            text_chars = await self._stream_to_slack(channel_id, thread_ts)
            status = await self._terminal_status()
        except Exception:
            logger.exception("Slack delivery crashed for run %s", self.record.id)
            await self._post_failure_notice(channel_id, thread_ts)
            return

        logger.info(
            "Slack delivery for run %s ended: status=%s text_chars=%s",
            self.record.id,
            status,
            text_chars,
        )
        if status is None:
            # The log ended but the record is not terminal (it vanished, or a
            # producer this build doesn't understand finalized it): the
            # streaming message is already stopped, so say *something* rather
            # than leaving the thread hanging. `cancelled` stays silent below
            # on purpose — the user stopped the run themselves.
            await self._post_failure_notice(channel_id, thread_ts)
        elif status is RunStatus.interrupted:
            await self._post_approvals(channel_id, thread_ts)
        elif status is RunStatus.success:
            await self._post_auxilia_link(channel_id, thread_ts)
        elif status in (
            RunStatus.error,
            RunStatus.timeout,
        ) and not await self._post_reauth_prompt_if_gated(channel_id, thread_ts):
            await self._post_failure_notice(channel_id, thread_ts)

    async def _stream_to_slack(self, channel_id: str, thread_ts: str) -> int:
        """Relay the event log into a Slack streaming message.

        Returns how many characters of answer text were streamed (0 is the
        tell-tale of an empty/never-answered turn). Always closes the
        streaming message — a mid-stream error must not leave an in-progress
        Slack message open. Returns once the log's terminal entry is read.
        """
        streamer = await self.client.chat_stream(
            channel=channel_id,
            thread_ts=thread_ts,
            recipient_team_id=self.delivery.get("team_id"),
            recipient_user_id=self.delivery.get("slack_user_id"),
        )
        adapter = SlackProtocolAdapter()
        text_chars = 0
        try:
            async for raw in RunService(self.redis).stream(self.record.id):
                event = decode_event(raw)
                if event is None:
                    continue
                if _is_failed_terminal(event):
                    error = (event["params"]["data"] or {}).get("error")
                    await streamer.append(
                        markdown_text=f"**`Error: {error or 'Unknown error'}`**\n\n"
                    )
                    continue
                for text in adapter.texts(event):
                    if not text.startswith("\n\n:"):  # tool labels aren't answer text
                        text_chars += len(text)
                    await streamer.append(markdown_text=text)
        finally:
            await streamer.stop()
        return text_chars

    async def _terminal_status(self) -> RunStatus | None:
        """The run's terminal status, from the durable record.

        `finalize` commits the record before it publishes the terminal entry,
        so once the log has ended the record is authoritative — and, unlike
        the protocol terminal event (which folds `cancelled` into
        `completed`), it distinguishes a user Stop from a clean finish."""
        record = await RunService(self.redis).get(self.record.id)
        return record.status if is_terminal(record.status) else None

    async def _post_reauth_prompt_if_gated(
        self, channel_id: str, thread_ts: str
    ) -> bool:
        """When the worker's OAuth pre-flight refused the run (a token expired
        between the enqueue-time check and execution), post the Connect button
        instead of the generic failure notice. Best-effort: False on any
        doubt, so the caller falls back to the notice."""
        try:
            record = await RunService(self.redis).get(self.record.id)
            if record.error != MCP_REAUTH_ERROR:
                return False
            async with AsyncSessionLocal() as db:
                thread = await db.get(ThreadDB, self.record.thread_id)
            if thread is None:
                return False
            connect_url = f"{auth_settings.FRONTEND_URL}/agents/{thread.agent_id}/chat"
            await self.client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                blocks=build_connect_prompt_blocks(connect_url),
                text="Please reconnect this agent's MCP servers on auxilia.",
            )
            return True
        except Exception:
            logger.exception(
                "Reauth prompt failed for run %s; posting generic notice",
                self.record.id,
            )
            return False

    async def _post_failure_notice(self, channel_id: str, thread_ts: str) -> None:
        """Tell the user the turn failed, so the thread is never left blank."""
        await self.client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=(
                "Sorry — something went wrong while generating a response. "
                "Please try again."
            ),
        )

    async def _post_approvals(self, channel_id: str, thread_ts: str) -> None:
        """Post a Block Kit approve/reject message per pending tool call."""
        async with get_checkpointer() as checkpointer:
            checkpoint = await checkpointer.aget_tuple(
                config={"configurable": {"thread_id": self.record.thread_id}}
            )
        interrupt = pending_interrupt(checkpoint)
        interrupt_id = interrupt.id if interrupt else None
        for request in pending_approval_requests(checkpoint):
            blocks = build_tool_approval_blocks(
                request["tool_call_id"],
                request["input"],
                interrupt_id=interrupt_id,
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


def _is_failed_terminal(event: dict[str, Any]) -> bool:
    """A root lifecycle `failed` event — the run's error, surfaced inline."""
    params = event.get("params") or {}
    data = params.get("data")
    return (
        event.get("method") == "lifecycle"
        and not params.get("namespace")
        and isinstance(data, dict)
        and data.get("event") == "failed"
    )
