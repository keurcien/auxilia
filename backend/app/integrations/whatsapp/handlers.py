import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.core.service import AgentService
from app.agents.models import EffectivePermission
from app.auth.settings import auth_settings
from app.exceptions import DomainError, DomainValidationError
from app.integrations.whatsapp.attachments import load_whatsapp_attachments
from app.integrations.whatsapp.client import WhatsAppAPIError, WhatsAppClient
from app.integrations.whatsapp.db_models import (
    WhatsAppContextMessageDB,
    WhatsAppThreadBindingDB,
)
from app.integrations.whatsapp.hitl import handle_approval_reply
from app.integrations.whatsapp.outbound import WhatsAppOutboundGateway
from app.integrations.whatsapp.repository import (
    WhatsAppContextRepository,
    WhatsAppIdentityRepository,
    WhatsAppOutboundMessageRepository,
    WhatsAppSessionRepository,
    WhatsAppThreadBindingRepository,
)
from app.integrations.whatsapp.service import (
    WhatsAppIdentityService,
    WhatsAppRuntimeConfig,
)
from app.model_providers.service import ModelService
from app.runtime.runs.service import RunService
from app.threads.models import ThreadSource
from app.threads.repository import ThreadRepository
from app.threads.service import ThreadService
from app.workspaces.repository import WorkspaceRepository


logger = logging.getLogger(__name__)
CONTEXT_RETENTION_DAYS = 30


def _link_prompt_text() -> str:
    settings_url = (
        f"{auth_settings.FRONTEND_URL.rstrip('/')}"
        "/settings?tab=profile&section=connected-accounts"
    )
    return (
        "Link your Auxilia account first. Generate a code in "
        f"Profile > Connected accounts:\n{settings_url}\n"
        "Then send /link CODE here."
    )


def _command(text: str) -> tuple[str | None, str | None]:
    if not text.startswith("/"):
        return None, None
    head, _, argument = text.partition(" ")
    return head.lower(), argument.strip() or None


def _message_text(message: dict[str, Any]) -> str:
    message_type = str(message.get("type") or "")
    content = message.get(message_type)
    if message_type == "text" and isinstance(content, dict):
        return str(content.get("body") or "").strip()
    if message_type in {"image", "document", "video"} and isinstance(content, dict):
        return str(content.get("caption") or "").strip()
    if message_type == "interactive" and isinstance(content, dict):
        reply = content.get("button_reply") or content.get("list_reply")
        if isinstance(reply, dict):
            return str(reply.get("id") or reply.get("title") or "").strip()
    if message_type == "button" and isinstance(content, dict):
        return str(content.get("payload") or content.get("text") or "").strip()
    return ""


def _sent_at(message: dict[str, Any]) -> datetime:
    try:
        return datetime.fromtimestamp(int(message.get("timestamp") or 0), tz=UTC)
    except TypeError, ValueError, OSError:
        return datetime.now(UTC)


async def handle_payload(
    db: AsyncSession,
    payload: dict[str, Any],
    *,
    config: WhatsAppRuntimeConfig,
) -> None:
    entries = payload.get("entry")
    if not isinstance(entries, list):
        return
    client = WhatsAppClient(config.access_token, config.phone_number_id)
    for entry in entries:
        changes = entry.get("changes") if isinstance(entry, dict) else None
        if not isinstance(changes, list):
            continue
        for change in changes:
            value = change.get("value") if isinstance(change, dict) else None
            if not isinstance(value, dict):
                continue
            contacts = value.get("contacts")
            names = (
                {
                    str(contact.get("wa_id")): str(
                        (contact.get("profile") or {}).get("name") or ""
                    )
                    for contact in contacts
                    if isinstance(contact, dict) and contact.get("wa_id")
                }
                if isinstance(contacts, list)
                else {}
            )
            await _handle_statuses(db, value, config)
            messages = value.get("messages")
            if not isinstance(messages, list):
                continue
            for message in messages:
                if isinstance(message, dict):
                    await _handle_message(
                        db,
                        message,
                        value=value,
                        display_name=names.get(str(message.get("from") or "")) or None,
                        config=config,
                        client=client,
                    )


async def _handle_statuses(
    db: AsyncSession,
    value: dict[str, Any],
    config: WhatsAppRuntimeConfig,
) -> None:
    statuses = value.get("statuses")
    if not isinstance(statuses, list):
        return
    repository = WhatsAppOutboundMessageRepository(db)
    for status in statuses:
        if not isinstance(status, dict):
            continue
        message_id = status.get("id")
        if not isinstance(message_id, str):
            continue
        row = await repository.get_message(config.id, message_id)
        if row is None:
            continue
        observed_at = _sent_at(status)
        if observed_at < row.status_at:
            continue
        row.status = str(status.get("status") or row.status)[:16]
        row.status_at = observed_at
        errors = status.get("errors")
        row.error = (
            str(errors[0].get("message") or errors[0].get("title") or "")
            if isinstance(errors, list) and errors and isinstance(errors[0], dict)
            else None
        )
        db.add(row)


async def _handle_message(
    db: AsyncSession,
    message: dict[str, Any],
    *,
    value: dict[str, Any],
    display_name: str | None,
    config: WhatsAppRuntimeConfig,
    client: WhatsAppClient,
) -> None:
    whatsapp_user_id = str(message.get("from") or "")
    message_id = str(message.get("id") or "")
    group_id = str(message.get("group_id") or value.get("group_id") or "")
    chat_id = group_id or whatsapp_user_id
    recipient_type = "group" if group_id else "individual"
    if not whatsapp_user_id or not message_id:
        return
    context_repository = WhatsAppContextRepository(db)
    if await context_repository.get_message(config.id, message_id) is not None:
        return
    sent_at = _sent_at(message)
    await WhatsAppSessionRepository(db).touch(
        config.id, recipient_type, chat_id, sent_at
    )
    gateway = WhatsAppOutboundGateway(
        db,
        config,
        recipient_id=chat_id,
        recipient_type=recipient_type,
    )
    if config.show_typing_indicator:
        try:
            await client.mark_read(message_id, show_typing_indicator=True)
        except WhatsAppAPIError:
            logger.info("Could not mark WhatsApp message read", exc_info=True)
    text = _message_text(message)
    await _observe_context(
        db,
        config,
        message_id=message_id,
        chat_id=chat_id,
        whatsapp_user_id=whatsapp_user_id,
        display_name=display_name,
        text=text,
        sent_at=sent_at,
    )
    interactive_id = text if text.startswith("th:") else None
    if interactive_id is not None:
        identity = await WhatsAppIdentityRepository(db).get_external(
            config.workspace_id, whatsapp_user_id
        )
        if identity is None:
            await gateway.send_text(_link_prompt_text())
            return
        try:
            await handle_approval_reply(
                db,
                action_id=interactive_id,
                config=config,
                identity=identity,
                chat_id=chat_id,
                recipient_type=recipient_type,
            )
        except DomainError:
            await gateway.send_text("This approval action is no longer valid.")
        return
    command, argument = _command(text)
    if command in {"/link", "/start"} and argument:
        if group_id:
            await gateway.send_text(
                "For security, link your account in a private chat with this number."
            )
            return
        try:
            await WhatsAppIdentityService(db, config.workspace_id).consume_link_code(
                whatsapp_user_id=whatsapp_user_id,
                phone_number=whatsapp_user_id,
                display_name=display_name,
                code=argument,
            )
        except DomainError as exc:
            await gateway.send_text(str(exc))
            return
        await gateway.send_text("Account linked. Send /new to start a conversation.")
        return
    identity = await WhatsAppIdentityRepository(db).get_external(
        config.workspace_id, whatsapp_user_id
    )
    if identity is None:
        await gateway.send_text(_link_prompt_text())
        return
    if command in {"/start", "/new"}:
        try:
            await _select_agent(
                db,
                config,
                user_id=identity.user_id,
                whatsapp_user_id=whatsapp_user_id,
                chat_id=chat_id,
            )
        except DomainError as exc:
            await gateway.send_text(str(exc))
            return
        await gateway.send_text("New conversation started. Send a message to begin.")
        return
    message_type = str(message.get("type") or "")
    if not text and message_type not in {"image", "document", "audio", "video"}:
        await gateway.send_text("This WhatsApp message type is not supported.")
        return
    try:
        binding = await _ensure_binding(
            db,
            config,
            user_id=identity.user_id,
            whatsapp_user_id=whatsapp_user_id,
            chat_id=chat_id,
        )
    except DomainError:
        await gateway.send_text("You do not have permission to use this agent.")
        return
    thread = await ThreadRepository(db, config.workspace_id).get(binding.thread_id)
    if thread is None:
        raise DomainValidationError("Conversation not found")
    membership = await WorkspaceRepository(db).get_membership(
        config.workspace_id, identity.user_id
    )
    if membership is None:
        raise DomainValidationError("Workspace membership not found")
    try:
        await AgentService(db, config.workspace_id).require_permission(
            thread.agent_id,
            user_id=identity.user_id,
            user_role=membership.role,
            user_team_id=membership.team_id,
            at_least=EffectivePermission.member,
            action="use this agent",
        )
    except DomainError:
        await gateway.send_text("You no longer have permission to use this agent.")
        return
    loaded = await load_whatsapp_attachments(client, message)
    if loaded.rejected_names:
        await gateway.send_text(
            "Some files could not be used: "
            + ", ".join(loaded.rejected_names)
            + ". Check the WhatsApp media limits and supported formats."
        )
    if loaded.content_blocks and not await ModelService(
        db, config.workspace_id
    ).supports_attachments(
        thread.model_id,
        documents=any(block.get("type") == "file" for block in loaded.content_blocks),
    ):
        await gateway.send_text(
            "The model selected for this conversation does not support these files."
        )
        return
    question = text or "Please review the attached file."
    prompt = await _context_prompt(
        db,
        config,
        binding,
        current_message_id=message_id,
        question=question,
    )
    content: str | list[dict[str, Any]] = prompt
    if loaded.content_blocks:
        content = [{"type": "text", "text": prompt}, *loaded.content_blocks]
    if thread.first_message_content is None:
        thread.first_message_content = question
        db.add(thread)
    await db.commit()
    delivery = {
        "channel": "whatsapp",
        "workspace_id": str(config.workspace_id),
        "whatsapp_connection_id": str(config.id),
        "recipient_id": chat_id,
        "recipient_type": recipient_type,
        "whatsapp_user_id": whatsapp_user_id,
        "inbound_message_id": message_id,
        "show_tool_callouts": config.show_tool_callouts,
        "force_enable_all_capabilities": (
            config.tool_discovery_mode.force_enable_all_capabilities
        ),
        "tool_discovery_mode": config.tool_discovery_mode.runtime_mode.value,
    }
    try:
        await RunService().create(
            thread_id=thread.id,
            user_id=str(identity.user_id),
            input={"messages": [{"type": "human", "content": content}]},
            delivery=delivery,
        )
    except DomainValidationError:
        await gateway.send_text("This conversation is already processing a request.")


async def _select_agent(
    db: AsyncSession,
    config: WhatsAppRuntimeConfig,
    *,
    user_id: UUID,
    whatsapp_user_id: str,
    chat_id: str,
) -> WhatsAppThreadBindingDB:
    membership = await WorkspaceRepository(db).get_membership(
        config.workspace_id, user_id
    )
    if membership is None:
        raise DomainValidationError("Workspace membership not found")
    await AgentService(db, config.workspace_id).require_permission(
        config.agent_id,
        user_id=user_id,
        user_role=membership.role,
        user_team_id=membership.team_id,
        at_least=EffectivePermission.member,
        action="use this agent",
    )
    repository = WhatsAppThreadBindingRepository(db)
    previous = await repository.get_external(config.id, chat_id, whatsapp_user_id)
    if previous is not None:
        await db.delete(previous)
        await db.flush()
    thread = await ThreadService(db, config.workspace_id).get_or_create(
        ts=str(uuid4()),
        agent_id=str(config.agent_id),
        question=None,
        user_id=str(user_id),
        source=ThreadSource.whatsapp,
        tool_mode=config.tool_discovery_mode.thread_mode,
    )
    binding = WhatsAppThreadBindingDB(
        whatsapp_connection_id=config.id,
        thread_id=thread.id,
        chat_id=chat_id,
        whatsapp_user_id=whatsapp_user_id,
    )
    db.add(binding)
    await db.flush()
    await db.refresh(binding)
    return binding


async def _ensure_binding(
    db: AsyncSession,
    config: WhatsAppRuntimeConfig,
    *,
    user_id: UUID,
    whatsapp_user_id: str,
    chat_id: str,
) -> WhatsAppThreadBindingDB:
    binding = await WhatsAppThreadBindingRepository(db).get_external(
        config.id, chat_id, whatsapp_user_id
    )
    if binding is not None:
        return binding
    return await _select_agent(
        db,
        config,
        user_id=user_id,
        whatsapp_user_id=whatsapp_user_id,
        chat_id=chat_id,
    )


async def _observe_context(
    db: AsyncSession,
    config: WhatsAppRuntimeConfig,
    *,
    message_id: str,
    chat_id: str,
    whatsapp_user_id: str,
    display_name: str | None,
    text: str,
    sent_at: datetime,
) -> None:
    repository = WhatsAppContextRepository(db)
    row = await repository.get_message(config.id, message_id)
    if row is None:
        row = WhatsAppContextMessageDB(
            whatsapp_connection_id=config.id,
            chat_id=chat_id,
            message_id=message_id,
            whatsapp_user_id=whatsapp_user_id,
            sent_at=sent_at,
            expires_at=sent_at + timedelta(days=CONTEXT_RETENTION_DAYS),
        )
    row.display_name = display_name
    row.text = text or None
    db.add(row)
    await db.flush()


async def _context_prompt(
    db: AsyncSession,
    config: WhatsAppRuntimeConfig,
    binding: WhatsAppThreadBindingDB,
    *,
    current_message_id: str,
    question: str,
) -> str:
    if binding.chat_id == binding.whatsapp_user_id:
        return question
    rows = await WhatsAppContextRepository(db).list_since(
        config.id, binding.chat_id, binding.last_context_at
    )
    relevant = [
        row for row in rows if row.text and row.message_id != current_message_id
    ]
    if not relevant:
        return question
    lines = [
        f"[Side-channel user {row.display_name or row.whatsapp_user_id or 'unknown'}]"
        f"\n{row.text}"
        for row in relevant
    ]
    binding.last_context_at = max(row.sent_at for row in rows)
    db.add(binding)
    return (
        '<side_channel_context source="whatsapp">\n'
        + "\n\n".join(lines)
        + "\n</side_channel_context>\n\n<current_request>\n"
        + question
        + "\n</current_request>"
    )
