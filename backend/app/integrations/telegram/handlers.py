import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.core.service import AgentService
from app.agents.models import EffectivePermission
from app.auth.settings import auth_settings
from app.exceptions import DomainError, DomainValidationError
from app.integrations.telegram.attachments import load_telegram_attachments
from app.integrations.telegram.client import TelegramClient
from app.integrations.telegram.db_models import (
    TelegramContextMessageDB,
    TelegramThreadBindingDB,
    TelegramUpdateStatus,
)
from app.integrations.telegram.hitl import handle_approval_callback
from app.integrations.telegram.repository import (
    TelegramContextRepository,
    TelegramIdentityRepository,
    TelegramThreadBindingRepository,
    TelegramUpdateRepository,
)
from app.integrations.telegram.service import (
    TelegramIdentityService,
    TelegramRuntimeConfig,
)
from app.model_providers.service import ModelService
from app.runtime.runs.service import RunService
from app.threads.models import ThreadSource
from app.threads.repository import ThreadRepository
from app.threads.service import ThreadService
from app.workspaces.repository import WorkspaceRepository


logger = logging.getLogger(__name__)
CONTEXT_RETENTION_DAYS = 30


def _display_name(user: dict[str, Any]) -> str | None:
    name = " ".join(
        part
        for part in (
            str(user.get("first_name") or "").strip(),
            str(user.get("last_name") or "").strip(),
        )
        if part
    )
    return name or str(user.get("username") or "").strip() or None


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
    return head.split("@", 1)[0].lower(), argument.strip() or None


def _is_group(chat: dict[str, Any]) -> bool:
    return chat.get("type") in {"group", "supergroup"}


def _is_addressed(
    message: dict[str, Any], config: TelegramRuntimeConfig, text: str
) -> bool:
    chat = message.get("chat") or {}
    if not _is_group(chat):
        return True
    command, _ = _command(text)
    if command:
        return True
    username = (config.bot_username or "").lower()
    mentioned = bool(username and f"@{username}" in text.lower())
    reply = message.get("reply_to_message")
    replied_to_bot = bool(
        isinstance(reply, dict)
        and isinstance(reply.get("from"), dict)
        and str(reply["from"].get("id") or "") == config.bot_id
    )
    return mentioned or replied_to_bot if config.require_mention_in_groups else True


async def handle_update(
    db: AsyncSession,
    update: dict[str, Any],
    *,
    config: TelegramRuntimeConfig,
    client: TelegramClient,
) -> None:
    callback = update.get("callback_query")
    if isinstance(callback, dict):
        await _handle_callback(db, callback, config=config, client=client)
        return
    message = update.get("message") or update.get("edited_message")
    if not isinstance(message, dict):
        return
    await _handle_message(db, message, config=config, client=client)


async def _observe_group_message(
    db: AsyncSession,
    message: dict[str, Any],
    config: TelegramRuntimeConfig,
) -> None:
    chat = message.get("chat") or {}
    if not _is_group(chat):
        return
    message_id = message.get("message_id")
    if not isinstance(message_id, int):
        return
    sender = message.get("from") or {}
    sent_at = datetime.fromtimestamp(
        int(message.get("date") or datetime.now(UTC).timestamp()), tz=UTC
    )
    chat_id = str(chat.get("id") or "")
    repository = TelegramContextRepository(db)
    row = await repository.get_message(config.id, chat_id, message_id)
    if row is None:
        row = TelegramContextMessageDB(
            telegram_bot_id=config.id,
            chat_id=chat_id,
            message_thread_id=str(message.get("message_thread_id") or ""),
            message_id=message_id,
            telegram_user_id=str(sender.get("id") or "") or None,
            sent_at=sent_at,
            expires_at=sent_at + timedelta(days=CONTEXT_RETENTION_DAYS),
        )
    row.display_name = _display_name(sender)
    row.text = str(message.get("text") or message.get("caption") or "") or None
    db.add(row)
    await db.flush()


async def _select_agent(
    db: AsyncSession,
    config: TelegramRuntimeConfig,
    *,
    user_id: UUID,
    telegram_user_id: str,
    chat_id: str,
    topic: str,
    agent_id: UUID,
) -> TelegramThreadBindingDB:
    membership = await WorkspaceRepository(db).get_membership(
        config.workspace_id, user_id
    )
    if membership is None:
        raise DomainValidationError("Workspace membership not found")
    await AgentService(db, config.workspace_id).require_permission(
        agent_id,
        user_id=user_id,
        user_role=membership.role,
        user_team_id=membership.team_id,
        at_least=EffectivePermission.member,
        action="use this agent",
    )
    bindings = TelegramThreadBindingRepository(db)
    previous = await bindings.get_external(config.id, chat_id, topic, telegram_user_id)
    if previous is not None:
        await db.delete(previous)
        await db.flush()
    thread = await ThreadService(db, config.workspace_id).get_or_create(
        ts=str(uuid4()),
        agent_id=str(agent_id),
        question=None,
        user_id=str(user_id),
        source=ThreadSource.telegram,
        tool_mode=config.tool_discovery_mode.thread_mode,
    )
    binding = TelegramThreadBindingDB(
        telegram_bot_id=config.id,
        thread_id=thread.id,
        chat_id=chat_id,
        message_thread_id=topic,
        telegram_user_id=telegram_user_id,
    )
    db.add(binding)
    await db.flush()
    await db.refresh(binding)
    return binding


async def _ensure_dedicated_binding(
    db: AsyncSession,
    config: TelegramRuntimeConfig,
    *,
    user_id: UUID,
    telegram_user_id: str,
    chat_id: str,
    topic: str,
) -> TelegramThreadBindingDB:
    bindings = TelegramThreadBindingRepository(db)
    binding = await bindings.get_external(config.id, chat_id, topic, telegram_user_id)
    if binding is not None:
        return binding
    return await _select_agent(
        db,
        config,
        user_id=user_id,
        telegram_user_id=telegram_user_id,
        chat_id=chat_id,
        topic=topic,
        agent_id=config.agent_id,
    )


async def _context_prompt(
    db: AsyncSession,
    config: TelegramRuntimeConfig,
    binding: TelegramThreadBindingDB,
    *,
    current_message_id: int | None,
    question: str,
) -> str:
    rows = await TelegramContextRepository(db).list_since(
        config.id,
        binding.chat_id,
        binding.message_thread_id,
        binding.last_context_message_id,
    )
    relevant = [
        row for row in rows if row.text and row.message_id != current_message_id
    ]
    if not relevant:
        return question
    lines = [
        f"[{row.sent_at.isoformat()}] {row.display_name or 'Telegram user'}: {row.text}"
        for row in relevant
    ]
    binding.last_context_message_id = max(row.message_id for row in rows)
    db.add(binding)
    return (
        '<side_channel_context source="telegram">\n'
        + "\n".join(lines)
        + "\n</side_channel_context>\n\n<current_request>\n"
        + question
        + "\n</current_request>"
    )


async def _handle_message(
    db: AsyncSession,
    message: dict[str, Any],
    *,
    config: TelegramRuntimeConfig,
    client: TelegramClient,
) -> None:
    chat = message.get("chat") or {}
    sender = message.get("from") or {}
    chat_id = str(chat.get("id") or "")
    telegram_user_id = str(sender.get("id") or "")
    topic = str(message.get("message_thread_id") or "")
    text = str(message.get("text") or message.get("caption") or "").strip()
    if not chat_id or not telegram_user_id:
        return
    await _observe_group_message(db, message, config)
    if not _is_addressed(message, config, text):
        return
    command, argument = _command(text)
    if command in {"/link", "/start"} and argument:
        if chat.get("type") != "private":
            await client.send_message(
                chat_id,
                "For security, link your account in a private chat with this bot.",
                message_thread_id=topic,
            )
            return
        try:
            await TelegramIdentityService(db, config.workspace_id).consume_link_code(
                telegram_user_id=telegram_user_id,
                username=str(sender.get("username") or "") or None,
                display_name=_display_name(sender),
                code=argument,
            )
        except DomainError as exc:
            await client.send_message(chat_id, str(exc), message_thread_id=topic)
            return
        await client.send_message(
            chat_id,
            "Account linked. Send /new to start a conversation.",
            message_thread_id=topic,
        )
        return
    identity = await TelegramIdentityRepository(db).get_external(
        config.workspace_id, telegram_user_id
    )
    if identity is None:
        await client.send_message(
            chat_id,
            _link_prompt_text(),
            message_thread_id=topic,
        )
        return
    if command in {"/start", "/new"}:
        try:
            await _select_agent(
                db,
                config,
                user_id=identity.user_id,
                telegram_user_id=telegram_user_id,
                chat_id=chat_id,
                topic=topic,
                agent_id=config.agent_id,
            )
        except DomainError as exc:
            await client.send_message(chat_id, str(exc), message_thread_id=topic)
            return
        await client.send_message(
            chat_id,
            "New conversation started. Send a message to begin.",
            message_thread_id=topic,
        )
        return
    if not text and not message.get("photo") and not message.get("document"):
        return
    try:
        binding = await _ensure_dedicated_binding(
            db,
            config,
            user_id=identity.user_id,
            telegram_user_id=telegram_user_id,
            chat_id=chat_id,
            topic=topic,
        )
    except DomainError:
        await client.send_message(
            chat_id,
            "You do not have permission to use this agent.",
            message_thread_id=topic,
        )
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
        await client.send_message(
            chat_id,
            "You no longer have permission to use this agent.",
            message_thread_id=topic,
        )
        return
    album_messages = [message]
    media_group_id = message.get("media_group_id")
    if isinstance(media_group_id, str) and media_group_id:
        await asyncio.sleep(1)
        album_rows = await TelegramUpdateRepository(db).list_media_group(
            config.id, media_group_id
        )
        album_messages = [
            item
            for row in album_rows
            if isinstance((item := row.payload.get("message")), dict)
        ] or [message]
        for row in album_rows:
            row.status = TelegramUpdateStatus.completed
            db.add(row)
        await db.flush()
    attachment_blocks: list[dict[str, Any]] = []
    rejected_names: list[str] = []
    for album_message in album_messages:
        loaded = await load_telegram_attachments(client, album_message)
        attachment_blocks.extend(loaded.content_blocks)
        rejected_names.extend(loaded.rejected_names)
    if rejected_names:
        await client.send_message(
            chat_id,
            "Some files could not be used: "
            + ", ".join(rejected_names)
            + ". Telegram downloads are limited to 20 MB and supported formats.",
            message_thread_id=topic,
        )
    if attachment_blocks and not await ModelService(
        db, config.workspace_id
    ).supports_attachments(
        thread.model_id,
        documents=any(block.get("type") == "file" for block in attachment_blocks),
    ):
        await client.send_message(
            chat_id,
            "The model selected for this conversation does not support these files.",
            message_thread_id=topic,
        )
        return
    if config.bot_username:
        text = text.replace(f"@{config.bot_username}", "").strip()
    album_caption = next(
        (
            str(item.get("caption") or "").strip()
            for item in album_messages
            if item.get("caption")
        ),
        "",
    )
    question = text or album_caption or "Please review the attached file."
    prompt = await _context_prompt(
        db,
        config,
        binding,
        current_message_id=(
            message.get("message_id")
            if isinstance(message.get("message_id"), int)
            else None
        ),
        question=question,
    )
    content: str | list[dict[str, Any]] = prompt
    if attachment_blocks:
        content = [{"type": "text", "text": prompt}, *attachment_blocks]
    if thread.first_message_content is None:
        thread.first_message_content = question
        db.add(thread)
    # The run opens its own session. Commit the thread/binding/context state
    # before handing it to the durable runtime.
    await db.commit()
    delivery = {
        "channel": "telegram",
        "workspace_id": str(config.workspace_id),
        "telegram_bot_id": str(config.id),
        "chat_id": chat_id,
        "message_thread_id": topic,
        "telegram_user_id": telegram_user_id,
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
        await client.send_message(
            chat_id,
            "This conversation is already processing a request.",
            message_thread_id=topic,
        )


async def _handle_callback(
    db: AsyncSession,
    callback: dict[str, Any],
    *,
    config: TelegramRuntimeConfig,
    client: TelegramClient,
) -> None:
    callback_id = str(callback.get("id") or "")
    sender = callback.get("from") or {}
    message = callback.get("message") or {}
    chat_id = str((message.get("chat") or {}).get("id") or "")
    telegram_user_id = str(sender.get("id") or "")
    data = str(callback.get("data") or "")
    if not callback_id or not telegram_user_id or not chat_id:
        return
    identity = await TelegramIdentityRepository(db).get_external(
        config.workspace_id, telegram_user_id
    )
    if identity is None:
        await client.answer_callback(callback_id, "Link your Auxilia account first")
        return
    try:
        if data.startswith("th:"):
            await handle_approval_callback(
                db,
                callback=callback,
                config=config,
                identity=identity,
                client=client,
            )
            return
    except DomainError, ValueError, KeyError:
        logger.info("Telegram callback is no longer valid", exc_info=True)
        await client.answer_callback(callback_id, "This action is no longer valid")
        return
    await client.answer_callback(callback_id)
