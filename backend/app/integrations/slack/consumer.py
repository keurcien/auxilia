"""Worker-side Slack delivery for durable runs.

A Slack turn has no client connection to ride the event log, so the worker spawns
a `SlackRunConsumer`: it subscribes to the run's event log (Agent Streaming
Protocol events, see `app/runtime/protocol/`), relays root text deltas and tool
labels into a Slack streaming message (`chat.startStream`/`appendStream`/
`stopStream` via `slack_sdk`'s `chat_stream`), and once the run is terminal
posts tool-approval blocks when interrupted. Successful turns finalize that
same streaming message with the configured instance link. This is the Slack
half of the durable runtime — the web tier only enqueues the run (see
`router.py`).
"""

import asyncio
import logging
from typing import Any, Final, Literal, NotRequired, TypedDict, cast
from uuid import UUID

from redis.asyncio import Redis
from slack_sdk.web.async_client import AsyncWebClient

from app.appearance.service import InstanceAppearanceService
from app.auth.settings import auth_settings
from app.database import AsyncSessionLocal, get_checkpointer
from app.integrations.slack.blocks import (
    build_connect_prompt_blocks,
    build_tool_approval_blocks,
    escape_mrkdwn,
    format_tool_streamer_label,
)
from app.integrations.slack.service import AgentSlackBotService
from app.integrations.slack.utils import get_slack_client
from app.runtime.checkpoints import checkpoint_thread_id
from app.runtime.hitl import load_interrupt_scope, pending_approval_requests
from app.runtime.protocol.wire import decode_event
from app.runtime.runs.delivery import DeliveryConsumer
from app.runtime.runs.models import RunDB
from app.runtime.runs.service import RunService
from app.runtime.runs.state import MCP_REAUTH_ERROR, RunStatus, is_terminal
from app.threads.repository import ThreadRepository


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
    workspace_id: str
    slack_bot_id: NotRequired[str | None]


def build_slack_run_consumer(record: RunDB) -> "SlackRunConsumer | None":
    """The `DeliveryFactory` for Slack: build a consumer iff the run is Slack-bound."""
    delivery = record.delivery
    if not delivery or delivery.get("channel") != SLACK_CHANNEL:
        return None
    if delivery.get("workspace_id") != str(record.workspace_id):
        logger.error("Slack delivery workspace mismatch for run %s", record.id)
        return None
    return SlackRunConsumer(record)


def build_slack_delivery(
    *,
    channel_id: str,
    thread_ts: str,
    slack_user_id: str,
    team_id: str | None,
    workspace_id: UUID,
    slack_bot_id: UUID | None = None,
) -> SlackDelivery:
    """The delivery descriptor stored on a Slack-bound run."""
    delivery: SlackDelivery = {
        "channel": SLACK_CHANNEL,
        "channel_id": channel_id,
        "thread_ts": thread_ts,
        "slack_user_id": slack_user_id,
        "team_id": team_id,
        "workspace_id": str(workspace_id),
    }
    if slack_bot_id is not None:
        delivery["slack_bot_id"] = str(slack_bot_id)
    return delivery


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

    def __init__(self, *, show_tool_callouts: bool = True) -> None:
        self._show_tool_callouts = show_tool_callouts
        self._tools_started: set[str] = set()
        self._tools_announced: set[str] = set()
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
        if (
            self._show_tool_callouts
            and method == "tools"
            and data.get("event") == "tool-started"
        ):
            tool_call_id = data.get("tool_call_id")
            tool_name = data.get("tool_name")
            if tool_call_id and tool_name and tool_call_id not in self._tools_started:
                self._tools_started.add(tool_call_id)
                normalized_name = str(tool_name)
                if normalized_name not in self._tools_announced:
                    self._tools_announced.add(normalized_name)
                    return [format_tool_streamer_label(normalized_name)]
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

    def __init__(
        self,
        record: RunDB,
        redis: Redis | None = None,
        client: AsyncWebClient | None = None,
    ):
        self.record = record
        # The factory only builds this consumer for a record whose delivery
        # carries channel == "slack", so the JSONB dict is a SlackDelivery.
        self.delivery = cast(SlackDelivery, record.delivery or {})
        self.redis = redis
        self.client = client
        self.app_name = "auxilia"
        self.show_tool_callouts = True

    @property
    def slack_client(self) -> AsyncWebClient:
        if self.client is None:
            raise RuntimeError("Slack client has not been initialized")
        return self.client

    async def _resolve_client(self) -> AsyncWebClient | None:
        if self.client is not None:
            return self.client
        for attempt in range(3):
            try:
                slack_bot_id = self.delivery.get("slack_bot_id")
                if slack_bot_id:
                    async with AsyncSessionLocal() as db:
                        config = await AgentSlackBotService(db).get_runtime(
                            UUID(slack_bot_id)
                        )
                        thread = await ThreadRepository(
                            db, self.record.workspace_id
                        ).get(self.record.thread_id)
                    if config is None:
                        return None
                    if (
                        config.workspace_id != self.record.workspace_id
                        or thread is None
                        or thread.agent_id != config.agent_id
                    ):
                        logger.error(
                            "Slack agent bot mismatch for run %s", self.record.id
                        )
                        return None
                    self.show_tool_callouts = config.show_tool_callouts
                    return AsyncWebClient(token=config.bot_token)
                return await get_slack_client(UUID(self.delivery["workspace_id"]))
            except Exception:
                if attempt == 2:
                    logger.exception(
                        "Slack client lookup failed for run %s", self.record.id
                    )
                    return None
                await asyncio.sleep(0.25 * (2**attempt))
        return None

    async def _resolve_app_name(self) -> str:
        try:
            async with AsyncSessionLocal() as db:
                return (await InstanceAppearanceService(db).get_settings()).app_name
        except Exception:  # noqa: BLE001 — branding lookup must not break delivery
            logger.warning(
                "Could not load the configured application name", exc_info=True
            )
            return "auxilia"

    async def run(self) -> None:
        client = await self._resolve_client()
        if client is None:
            logger.warning(
                "Slack delivery skipped for run %s: Slack is not configured",
                self.record.id,
            )
            return
        self.client = client
        self.app_name = await self._resolve_app_name()
        channel_id = self.delivery["channel_id"]
        thread_ts = self.delivery["thread_ts"]
        logger.info(
            "Slack delivery starting for run %s (channel=%s, thread_ts=%s)",
            self.record.id,
            channel_id,
            thread_ts,
        )
        marker_ts = await self._post_working_marker(channel_id, thread_ts)
        try:
            try:
                text_chars, status = await self._stream_to_slack(channel_id, thread_ts)
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
            elif status in (
                RunStatus.error,
                RunStatus.timeout,
            ) and not await self._post_reauth_prompt_if_gated(channel_id, thread_ts):
                await self._post_failure_notice(channel_id, thread_ts)
        finally:
            await self._remove_working_marker(channel_id, marker_ts)

    async def _post_working_marker(self, channel_id: str, thread_ts: str) -> str | None:
        """Post a temporary progress marker for agent-specific Slack bots."""
        if not self.delivery.get("slack_bot_id"):
            return None
        try:
            response = await self.slack_client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text=":hourglass_flowing_sand: Working on it…",
            )
            message_ts = response.get("ts")
            return str(message_ts) if message_ts else None
        except Exception:  # noqa: BLE001 — cosmetic marker must never fail delivery
            logger.warning(
                "Could not post Slack progress marker for run %s",
                self.record.id,
                exc_info=True,
            )
            return None

    async def _remove_working_marker(
        self, channel_id: str, message_ts: str | None
    ) -> None:
        """Best-effort cleanup of the temporary progress marker."""
        if message_ts is None:
            return
        try:
            await self.slack_client.chat_delete(channel=channel_id, ts=message_ts)
        except Exception:  # noqa: BLE001 — cosmetic cleanup must never fail delivery
            logger.warning(
                "Could not remove Slack progress marker for run %s",
                self.record.id,
                exc_info=True,
            )

    async def _stream_to_slack(
        self, channel_id: str, thread_ts: str
    ) -> tuple[int, RunStatus | None]:
        """Relay the event log into a Slack streaming message.

        Returns the answer character count and terminal status. Successful
        turns include the instance link in the finalized message. Always
        closes the stream, including after a mid-stream error.
        """
        streamer = await self.slack_client.chat_stream(
            channel=channel_id,
            thread_ts=thread_ts,
            recipient_team_id=self.delivery.get("team_id"),
            recipient_user_id=self.delivery.get("slack_user_id"),
        )
        adapter = SlackProtocolAdapter(
            show_tool_callouts=self.show_tool_callouts,
        )
        text_chars = 0
        status: RunStatus | None = None
        final_blocks: list[dict[str, Any]] | None = None
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
                    if not text.startswith("\n> "):  # tool labels aren't answer text
                        text_chars += len(text)
                    await streamer.append(markdown_text=text)
            status = await self._terminal_status()
            if status is RunStatus.success:
                final_blocks = await self._instance_link_blocks()
        finally:
            await streamer.stop(blocks=final_blocks)
        return text_chars, status

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
                thread = await ThreadRepository(db, self.record.workspace_id).get(
                    self.record.thread_id
                )
            if thread is None:
                return False
            connect_url = f"{auth_settings.FRONTEND_URL}/agents/{thread.agent_id}/chat"
            await self.slack_client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                blocks=build_connect_prompt_blocks(connect_url, self.app_name),
                text=(f"Please reconnect this agent's MCP servers on {self.app_name}."),
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
        await self.slack_client.chat_postMessage(
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
            scope = await load_interrupt_scope(
                checkpointer,
                checkpoint_thread_id(self.record.workspace_id, self.record.thread_id),
            )
        if scope is None:
            return
        # A subagent's gated calls live in its own checkpoint; the card says
        # which subagent asked, since the tool name alone is ambiguous.
        subagent = scope.subagent_type
        for request in pending_approval_requests(
            scope.root, scope.state, interrupt_id=scope.interrupt.id
        ):
            blocks = build_tool_approval_blocks(
                request["tool_call_id"],
                request["input"],
                interrupt_id=scope.interrupt.id,
                subagent=subagent,
            )
            text = f"Approve {request['tool_name']}?"
            if subagent:
                text = f"Approve {request['tool_name']} for {subagent}?"
            await self.slack_client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                blocks=blocks,
                text=text,
            )

    async def _instance_link_blocks(self) -> list[dict[str, Any]] | None:
        """Build the footer rendered inside the finalized streaming message."""
        async with AsyncSessionLocal() as db:
            thread = await ThreadRepository(db, self.record.workspace_id).get(
                self.record.thread_id
            )
        if thread is None:
            return None
        url = f"{auth_settings.FRONTEND_URL}/agents/{thread.agent_id}/chat/{thread.id}"
        return [
            {"type": "divider"},
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"<{url}|*View in {escape_mrkdwn(self.app_name)}*>",
                    }
                ],
            },
        ]


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
