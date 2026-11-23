import logging
import time
from typing import Any, Final, Literal, NotRequired, TypedDict, cast
from uuid import UUID

from redis.asyncio import Redis

from app.artifacts.service import ArtifactService
from app.auth.settings import auth_settings
from app.database import AsyncSessionLocal, get_checkpointer
from app.exceptions import DomainValidationError
from app.integrations.channels.protocol import ChannelProtocolAdapter
from app.integrations.whatsapp.client import WhatsAppAPIError, WhatsAppClient
from app.integrations.whatsapp.db_models import (
    WhatsAppApprovalActionDB,
    WhatsAppDeliveryCursorDB,
)
from app.integrations.whatsapp.outbound import WhatsAppOutboundGateway
from app.integrations.whatsapp.repository import (
    WhatsAppApprovalRepository,
    WhatsAppDeliveryCursorRepository,
)
from app.integrations.whatsapp.service import WhatsAppConnectionService
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
WHATSAPP_CHANNEL: Final = "whatsapp"
WHATSAPP_TEXT_CHUNK: Final = 4000
WHATSAPP_UPLOAD_LIMIT: Final = 100 * 1024 * 1024


class WhatsAppDelivery(TypedDict):
    channel: Literal["whatsapp"]
    workspace_id: str
    whatsapp_connection_id: str
    recipient_id: str
    recipient_type: str
    whatsapp_user_id: str
    inbound_message_id: NotRequired[str]
    show_tool_callouts: NotRequired[bool]
    force_enable_all_capabilities: NotRequired[bool]
    tool_discovery_mode: NotRequired[str]


def build_whatsapp_run_consumer(record: RunDB) -> WhatsAppRunConsumer | None:
    delivery = record.delivery
    if not delivery or delivery.get("channel") != WHATSAPP_CHANNEL:
        return None
    if delivery.get("workspace_id") != str(record.workspace_id):
        logger.error("WhatsApp delivery workspace mismatch for run %s", record.id)
        return None
    try:
        UUID(str(delivery["whatsapp_connection_id"]))
    except KeyError, ValueError:
        logger.error("WhatsApp delivery connection is invalid for run %s", record.id)
        return None
    return WhatsAppRunConsumer(record)


class WhatsAppRunConsumer(DeliveryConsumer):
    def __init__(self, record: RunDB, redis: Redis | None = None):
        self.record = record
        self.delivery = cast(WhatsAppDelivery, record.delivery or {})
        self.redis = redis
        self.show_auxilia_link = True

    async def _config(self):
        async with AsyncSessionLocal() as db:
            config = await WhatsAppConnectionService(db).get_runtime(
                UUID(self.delivery["whatsapp_connection_id"])
            )
        if config is not None:
            self.show_auxilia_link = config.show_auxilia_link
        return config

    async def run(self) -> None:
        config = await self._config()
        if config is None:
            logger.warning("WhatsApp delivery skipped for run %s", self.record.id)
            return
        cursor = await self._cursor()
        if cursor.completed:
            return
        try:
            text, adapter = await self._stream(config)
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
            chunks = [
                final[offset : offset + WHATSAPP_TEXT_CHUNK]
                for offset in range(0, len(final), WHATSAPP_TEXT_CHUNK)
            ]
            for index, chunk in enumerate(chunks):
                if index < len(cursor.sent_message_ids):
                    continue
                message_id = await self._send_text(config, chunk)
                cursor.sent_message_ids.append(message_id)
                await self._save_cursor(cursor)
            await self._post_artifacts(config, adapter.artifact_ids, cursor)
            if record.status is RunStatus.interrupted:
                await self._post_approvals(config)
            elif record.status is RunStatus.success:
                await self._post_auxilia_link(config)
            elif record.status in {
                RunStatus.error,
                RunStatus.timeout,
            } and is_mcp_reauth_error(record.error):
                await self._send_text(
                    config,
                    "Reconnect this agent's MCP servers in Auxilia, then try again.",
                )
            cursor.completed = True
            await self._save_cursor(cursor)
        except DomainValidationError:
            logger.info(
                "WhatsApp delivery stopped because the service window is unavailable"
            )
        except Exception:
            logger.exception("WhatsApp delivery crashed for run %s", self.record.id)
            try:
                await self._send_text(
                    config,
                    "Sorry, I could not deliver the complete response. "
                    "Open the conversation in Auxilia to continue.",
                )
            except Exception:
                logger.exception(
                    "WhatsApp fallback delivery failed for run %s", self.record.id
                )

    async def _stream(self, config) -> tuple[str, ChannelProtocolAdapter]:
        adapter = ChannelProtocolAdapter(
            show_tool_callouts=self.delivery.get("show_tool_callouts", True)
        )
        text = ""
        last_typing = time.monotonic()
        inbound_message_id = self.delivery.get("inbound_message_id")
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
            if (
                inbound_message_id
                and config.show_typing_indicator
                and now - last_typing >= 20
            ):
                try:
                    await WhatsAppClient(
                        config.access_token, config.phone_number_id
                    ).mark_read(inbound_message_id, show_typing_indicator=True)
                except WhatsAppAPIError:
                    logger.info(
                        "Could not refresh WhatsApp typing indicator", exc_info=True
                    )
                last_typing = now
        return text, adapter

    async def _send_text(self, config, text: str) -> str:
        async with AsyncSessionLocal() as db:
            gateway = WhatsAppOutboundGateway(
                db,
                config,
                recipient_id=self.delivery["recipient_id"],
                recipient_type=self.delivery["recipient_type"],
            )
            message_id = await gateway.send_text(text)
            await db.commit()
            return message_id

    async def _post_artifacts(
        self,
        config,
        artifact_ids: list[UUID],
        cursor: WhatsAppDeliveryCursorDB,
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
                    if len(data) > WHATSAPP_UPLOAD_LIMIT:
                        failed = True
                        continue
                    gateway = WhatsAppOutboundGateway(
                        db,
                        config,
                        recipient_id=self.delivery["recipient_id"],
                        recipient_type=self.delivery["recipient_type"],
                    )
                    await gateway.send_media(
                        filename=row.filename,
                        content=data,
                        mime_type=row.mime_type,
                        caption=row.title,
                    )
                    await db.commit()
                cursor.sent_artifact_ids.append(str(artifact_id))
                await self._save_cursor(cursor)
            except Exception:
                failed = True
                logger.exception(
                    "Could not upload artifact %s for WhatsApp run %s",
                    artifact_id,
                    self.record.id,
                )
        if failed:
            await self._send_text(
                config,
                "A generated file could not be attached here. "
                "Open the conversation in Auxilia to download it.",
            )

    async def _post_approvals(self, config) -> None:
        async with get_checkpointer() as checkpointer:
            scope = await load_interrupt_scope(
                checkpointer,
                checkpoint_thread_id(self.record.workspace_id, self.record.thread_id),
            )
        if scope is None:
            return
        if is_elicitation(scope.interrupt.value):
            tool_name = scope.interrupt.value.get("tool_name") or "An MCP tool"
            await self._send_text(
                config,
                f"{tool_name} needs more information. Answer in Auxilia.",
            )
            await self._post_auxilia_link(config, elicitation=True)
            return
        if scope.interrupt.id is None:
            return
        requests = pending_approval_requests(
            scope.root, scope.state, interrupt_id=scope.interrupt.id
        )
        interrupt_id = scope.interrupt.id
        async with AsyncSessionLocal() as db:
            repository = WhatsAppApprovalRepository(db)
            existing = {
                row.tool_call_id: row
                for row in await repository.list_interrupt(
                    self.record.thread_id, interrupt_id
                )
            }
            rows: list[WhatsAppApprovalActionDB] = []
            for request in requests:
                row = existing.get(request["tool_call_id"])
                if row is None:
                    row = WhatsAppApprovalActionDB(
                        whatsapp_connection_id=UUID(
                            self.delivery["whatsapp_connection_id"]
                        ),
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
                gateway = WhatsAppOutboundGateway(
                    db,
                    config,
                    recipient_id=self.delivery["recipient_id"],
                    recipient_type=self.delivery["recipient_type"],
                )
                if self.delivery["recipient_type"] == "individual":
                    row.message_id = await gateway.send_approval(
                        f"Approve {request['tool_name']}{subagent}?\n{details[:900]}",
                        row.token,
                    )
                else:
                    await self._post_auxilia_link(config, approval=True)
                    row.message_id = "web"
                db.add(row)
                await db.commit()

    async def _post_auxilia_link(
        self,
        config,
        *,
        approval: bool = False,
        elicitation: bool = False,
    ) -> None:
        if not self.show_auxilia_link and not approval and not elicitation:
            return
        async with AsyncSessionLocal() as db:
            thread = await ThreadRepository(db, self.record.workspace_id).get(
                self.record.thread_id
            )
        if thread is None:
            return
        prefix = (
            "Approve in Auxilia"
            if approval
            else "Answer in Auxilia"
            if elicitation
            else "View in Auxilia"
        )
        await self._send_text(
            config,
            f"{prefix}: {auth_settings.FRONTEND_URL}/agents/"
            f"{thread.agent_id}/chat/{thread.id}",
        )

    async def _cursor(self) -> WhatsAppDeliveryCursorDB:
        async with AsyncSessionLocal() as db:
            repository = WhatsAppDeliveryCursorRepository(db)
            row = await repository.get_for_run(self.record.id)
            if row is None:
                row = WhatsAppDeliveryCursorDB(
                    run_id=self.record.id,
                    whatsapp_connection_id=UUID(
                        self.delivery["whatsapp_connection_id"]
                    ),
                )
                db.add(row)
                await db.flush()
            await db.commit()
            await db.refresh(row)
            return row

    async def _save_cursor(self, cursor: WhatsAppDeliveryCursorDB) -> None:
        async with AsyncSessionLocal() as db:
            row = await WhatsAppDeliveryCursorRepository(db).get_for_run(self.record.id)
            if row is None:
                return
            row.sent_message_ids = list(cursor.sent_message_ids)
            row.sent_artifact_ids = list(cursor.sent_artifact_ids)
            row.completed = cursor.completed
            db.add(row)
            await db.commit()


def _is_failed_terminal(event: dict[str, Any]) -> bool:
    params = event.get("params") or {}
    data = params.get("data")
    return (
        event.get("method") == "lifecycle"
        and not params.get("namespace")
        and isinstance(data, dict)
        and data.get("event") == "run-failed"
    )
