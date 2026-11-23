import logging
import time
from typing import Any, Final, Literal, NotRequired, TypedDict, cast
from uuid import UUID

from redis.asyncio import Redis

from app.artifacts.service import ArtifactService
from app.auth.settings import auth_settings
from app.database import AsyncSessionLocal, get_checkpointer
from app.integrations.channels.protocol import ChannelProtocolAdapter
from app.integrations.telegram.client import TelegramClient
from app.integrations.telegram.db_models import (
    TelegramApprovalActionDB,
    TelegramDeliveryCursorDB,
)
from app.integrations.telegram.keyboards import approval_keyboard
from app.integrations.telegram.repository import (
    TelegramApprovalRepository,
    TelegramDeliveryCursorRepository,
)
from app.integrations.telegram.service import TelegramBotService
from app.runtime.checkpoints import checkpoint_thread_id
from app.runtime.hitl import load_interrupt_scope, pending_approval_requests
from app.runtime.protocol.events import is_elicitation
from app.runtime.protocol.wire import decode_event
from app.runtime.runs.delivery import DeliveryConsumer
from app.runtime.runs.models import RunDB
from app.runtime.runs.service import RunService
from app.runtime.runs.state import RunStatus, is_mcp_reauth_error
from app.threads.repository import ThreadRepository


logger = logging.getLogger(__name__)
TELEGRAM_CHANNEL: Final = "telegram"
TELEGRAM_TEXT_CHUNK: Final = 3900
TELEGRAM_UPLOAD_LIMIT: Final = 50 * 1024 * 1024


class TelegramDelivery(TypedDict):
    channel: Literal["telegram"]
    workspace_id: str
    telegram_bot_id: str
    chat_id: str
    message_thread_id: str
    telegram_user_id: str
    show_tool_callouts: NotRequired[bool]
    force_enable_all_capabilities: NotRequired[bool]
    tool_discovery_mode: NotRequired[str]


def build_telegram_run_consumer(record: RunDB) -> TelegramRunConsumer | None:
    delivery = record.delivery
    if not delivery or delivery.get("channel") != TELEGRAM_CHANNEL:
        return None
    if delivery.get("workspace_id") != str(record.workspace_id):
        logger.error("Telegram delivery workspace mismatch for run %s", record.id)
        return None
    try:
        UUID(str(delivery["telegram_bot_id"]))
    except KeyError, ValueError:
        logger.error("Telegram delivery bot is invalid for run %s", record.id)
        return None
    return TelegramRunConsumer(record)


class TelegramRunConsumer(DeliveryConsumer):
    def __init__(self, record: RunDB, redis: Redis | None = None):
        self.record = record
        self.delivery = cast(TelegramDelivery, record.delivery or {})
        self.redis = redis
        self.show_auxilia_link = True

    async def _client(self) -> TelegramClient | None:
        async with AsyncSessionLocal() as db:
            config = await TelegramBotService(db).get_runtime(
                UUID(self.delivery["telegram_bot_id"])
            )
        if config is not None:
            self.show_auxilia_link = config.show_auxilia_link
        return TelegramClient(config.bot_token) if config else None

    async def run(self) -> None:
        client = await self._client()
        if client is None:
            logger.warning("Telegram delivery skipped for run %s", self.record.id)
            return
        chat_id = self.delivery["chat_id"]
        topic = self.delivery["message_thread_id"]
        cursor = await self._cursor()
        if cursor.completed:
            return
        try:
            await client.send_chat_action(chat_id, "typing", message_thread_id=topic)
            if cursor.primary_message_id is None:
                placeholder = await client.send_message(
                    chat_id, "Thinking...", message_thread_id=topic
                )
                cursor.primary_message_id = int(placeholder["message_id"])
                await self._save_cursor(cursor)
            message_id = cursor.primary_message_id
            text, adapter = await self._stream(client, chat_id, message_id)
            record = await RunService(self.redis).get(self.record.id)
            final = text.strip()
            if record.status is RunStatus.interrupted and not final:
                final = "Approval required."
            elif record.status is RunStatus.cancelled and not final:
                final = "Stopped."
            elif record.status in {RunStatus.error, RunStatus.timeout} and not final:
                final = "Sorry, something went wrong while generating a response."
            elif not final:
                final = "Done."
            await client.edit_message(chat_id, message_id, final[:TELEGRAM_TEXT_CHUNK])
            extra_chunks = [
                final[offset : offset + TELEGRAM_TEXT_CHUNK]
                for offset in range(
                    TELEGRAM_TEXT_CHUNK, len(final), TELEGRAM_TEXT_CHUNK
                )
            ]
            for index, chunk in enumerate(extra_chunks):
                if index < len(cursor.extra_message_ids):
                    await client.edit_message(
                        chat_id, cursor.extra_message_ids[index], chunk
                    )
                else:
                    sent = await client.send_message(
                        chat_id, chunk, message_thread_id=topic
                    )
                    cursor.extra_message_ids.append(int(sent["message_id"]))
                    await self._save_cursor(cursor)
            await self._post_artifacts(client, adapter.artifact_ids, cursor)
            if record.status is RunStatus.interrupted:
                await self._post_approvals(client)
            elif record.status is RunStatus.success:
                await self._post_auxilia_link(client)
            elif record.status in {
                RunStatus.error,
                RunStatus.timeout,
            } and is_mcp_reauth_error(record.error):
                await client.send_message(
                    chat_id,
                    "Reconnect this agent's MCP servers in Auxilia, then try again.",
                    message_thread_id=topic,
                )
            cursor.completed = True
            await self._save_cursor(cursor)
        except Exception:
            logger.exception("Telegram delivery crashed for run %s", self.record.id)
            try:
                await client.send_message(
                    chat_id,
                    "Sorry, I could not deliver the complete response. "
                    "Open the conversation in Auxilia to continue.",
                    message_thread_id=topic,
                )
            except Exception:
                logger.exception(
                    "Telegram fallback delivery failed for run %s", self.record.id
                )

    async def _stream(
        self, client: TelegramClient, chat_id: str, message_id: int
    ) -> tuple[str, ChannelProtocolAdapter]:
        adapter = ChannelProtocolAdapter(
            show_tool_callouts=self.delivery.get("show_tool_callouts", True)
        )
        text = ""
        last_edit = time.monotonic()
        last_sent = ""
        async for raw in RunService(self.redis).stream(self.record.id):
            event = decode_event(raw)
            if event is None:
                continue
            if _is_failed_terminal(event):
                error = (event["params"]["data"] or {}).get("error")
                if error and not is_mcp_reauth_error(str(error)):
                    text += "\n\nError: The run could not be completed."
            else:
                text += "".join(adapter.texts(event))
            now = time.monotonic()
            visible = text.strip()[:TELEGRAM_TEXT_CHUNK]
            if visible and visible != last_sent and now - last_edit >= 1.2:
                await client.edit_message(chat_id, message_id, visible)
                last_sent = visible
                last_edit = now
        return text, adapter

    async def _post_artifacts(
        self,
        client: TelegramClient,
        artifact_ids: list[UUID],
        cursor: TelegramDeliveryCursorDB,
    ) -> None:
        failed = False
        for artifact_id in artifact_ids:
            if str(artifact_id) in cursor.sent_artifact_ids:
                continue
            try:
                async with AsyncSessionLocal() as db:
                    row, data = await ArtifactService(
                        db, self.record.workspace_id
                    ).content(self.record.thread_id, artifact_id)
                if len(data) > TELEGRAM_UPLOAD_LIMIT:
                    failed = True
                    continue
                if row.mime_type.startswith("image/") and len(data) <= 10 * 1024 * 1024:
                    await client.send_photo(
                        self.delivery["chat_id"],
                        row.filename,
                        data,
                        message_thread_id=self.delivery["message_thread_id"],
                        caption=row.title,
                    )
                else:
                    await client.send_document(
                        self.delivery["chat_id"],
                        row.filename,
                        data,
                        message_thread_id=self.delivery["message_thread_id"],
                        caption=row.title,
                    )
                cursor.sent_artifact_ids.append(str(artifact_id))
                await self._save_cursor(cursor)
            except Exception:
                failed = True
                logger.exception(
                    "Could not upload artifact %s for Telegram run %s",
                    artifact_id,
                    self.record.id,
                )
        if failed:
            await client.send_message(
                self.delivery["chat_id"],
                "A generated file could not be attached here. "
                "Open the conversation in Auxilia to download it.",
                message_thread_id=self.delivery["message_thread_id"],
            )

    async def _cursor(self) -> TelegramDeliveryCursorDB:
        async with AsyncSessionLocal() as db:
            repository = TelegramDeliveryCursorRepository(db)
            row = await repository.get_for_run(self.record.id)
            if row is None:
                row = TelegramDeliveryCursorDB(
                    run_id=self.record.id,
                    telegram_bot_id=UUID(self.delivery["telegram_bot_id"]),
                )
                db.add(row)
                await db.flush()
            await db.commit()
            await db.refresh(row)
            return row

    async def _save_cursor(self, cursor: TelegramDeliveryCursorDB) -> None:
        async with AsyncSessionLocal() as db:
            row = await TelegramDeliveryCursorRepository(db).get_for_run(self.record.id)
            if row is None:
                return
            row.primary_message_id = cursor.primary_message_id
            row.extra_message_ids = list(cursor.extra_message_ids)
            row.sent_artifact_ids = list(cursor.sent_artifact_ids)
            row.completed = cursor.completed
            db.add(row)
            await db.commit()

    async def _post_approvals(self, client: TelegramClient) -> None:
        async with get_checkpointer() as checkpointer:
            scope = await load_interrupt_scope(
                checkpointer,
                checkpoint_thread_id(self.record.workspace_id, self.record.thread_id),
            )
        if scope is None:
            return
        if is_elicitation(scope.interrupt.value):
            tool_name = scope.interrupt.value.get("tool_name") or "An MCP tool"
            await client.send_message(
                self.delivery["chat_id"],
                f"{tool_name} needs more information. Answer in Auxilia.",
                message_thread_id=self.delivery["message_thread_id"],
            )
            await self._post_auxilia_link(client, force=True)
            return
        requests = pending_approval_requests(
            scope.root, scope.state, interrupt_id=scope.interrupt.id
        )
        interrupt_id = scope.interrupt.id
        if interrupt_id is None:
            return
        async with AsyncSessionLocal() as db:
            repository = TelegramApprovalRepository(db)
            existing = {
                row.tool_call_id: row
                for row in await repository.list_interrupt(
                    self.record.thread_id, interrupt_id
                )
            }
            rows: list[TelegramApprovalActionDB] = []
            for request in requests:
                row = existing.get(request["tool_call_id"])
                if row is None:
                    row = TelegramApprovalActionDB(
                        telegram_bot_id=UUID(self.delivery["telegram_bot_id"]),
                        workspace_id=self.record.workspace_id,
                        user_id=self.record.user_id,
                        thread_id=self.record.thread_id,
                        interrupt_id=interrupt_id,
                        tool_call_id=request["tool_call_id"],
                    )
                    db.add(row)
                    await db.flush()
                rows.append(row)
            await db.commit()
            for request, row in zip(requests, rows, strict=True):
                if row.message_id is not None or row.decision is not None:
                    continue
                subagent = f" for {scope.subagent_type}" if scope.subagent_type else ""
                details = str(request.get("input") or "")
                sent = await client.send_message(
                    self.delivery["chat_id"],
                    f"Approve {request['tool_name']}{subagent}?\n{details[:3000]}",
                    message_thread_id=self.delivery["message_thread_id"],
                    reply_markup=approval_keyboard(row.token),
                )
                row.message_id = int(sent["message_id"])
                db.add(row)
                await db.commit()

    async def _post_auxilia_link(
        self, client: TelegramClient, *, force: bool = False
    ) -> None:
        if not self.show_auxilia_link and not force:
            return
        async with AsyncSessionLocal() as db:
            thread = await ThreadRepository(db, self.record.workspace_id).get(
                self.record.thread_id
            )
        if thread is None:
            return
        await client.send_message(
            self.delivery["chat_id"],
            f"View in Auxilia: {auth_settings.FRONTEND_URL}/agents/"
            f"{thread.agent_id}/chat/{thread.id}",
            message_thread_id=self.delivery["message_thread_id"],
        )


def _is_failed_terminal(event: dict[str, Any]) -> bool:
    params = event.get("params") or {}
    data = params.get("data")
    return (
        event.get("method") == "lifecycle"
        and not params.get("namespace")
        and isinstance(data, dict)
        and data.get("event") == "failed"
    )
