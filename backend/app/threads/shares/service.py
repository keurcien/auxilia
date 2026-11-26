import base64
import hashlib
import hmac
import logging
from typing import Any
from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.core.repository import AgentRepository
from app.agents.models import AgentMCPServerDB, ToolDiscoveryMode, ToolStatus
from app.artifacts.models import ArtifactDB
from app.artifacts.repository import ArtifactRepository
from app.artifacts.service import ArtifactGoneError, ArtifactService
from app.auth.settings import auth_settings
from app.database import get_checkpointer, get_db
from app.exceptions import DomainValidationError, NotFoundError, PermissionDeniedError
from app.mcp.servers.models import MCPServerDB, MCPServerImageDB
from app.mcp.servers.repository import MCPServerRepository
from app.model_providers.whitelist import get_whitelist
from app.runtime.api.costs import CostService
from app.runtime.checkpoints import checkpoint_thread_id, get_checkpoint_state
from app.runtime.hitl import pending_interrupt
from app.runtime.protocol.messages import (
    public_image_gallery,
    serialize_public_message,
)
from app.runtime.runs.repository import RunRepository
from app.runtime.runs.schemas import RunResponse
from app.runtime.toolset import sanitize_tool_name
from app.threads.models import ThreadDB
from app.threads.repository import ThreadRepository
from app.threads.shares.models import (
    ConversationShareArtifactDB,
    ConversationShareDB,
)
from app.threads.shares.repository import ConversationShareRepository
from app.threads.shares.schemas import (
    ConversationShareCreateDB,
    ConversationShareResponse,
    PublicAgent,
    PublicArtifact,
    PublicConversationResponse,
    PublicToolServer,
)


logger = logging.getLogger(__name__)


def _share_token(share_id: UUID) -> str:
    digest = hmac.new(
        auth_settings.JWT_SECRET_KEY.encode(),
        f"conversation-share:{share_id}".encode(),
        hashlib.sha256,
    ).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def _used_tool_names(messages: list[dict[str, Any]]) -> set[str]:
    used: set[str] = set()
    for message in messages:
        tool_calls = message.get("tool_calls")
        if not isinstance(tool_calls, list):
            continue
        for tool_call in tool_calls:
            tool_name = tool_call.get("name") if isinstance(tool_call, dict) else None
            if isinstance(tool_name, str):
                used.add(tool_name)
    return used


def _runtime_tool_owners(
    bindings: list[AgentMCPServerDB],
    servers_by_id: dict[UUID, MCPServerDB],
    disabled_tools: dict[str, list[str]],
) -> dict[str, UUID]:
    used_names: set[str] = set()
    owners: dict[str, UUID] = {}
    for binding in bindings:
        server = servers_by_id.get(binding.mcp_server_id)
        if server is None:
            continue
        for tool_name, status in (binding.tools or {}).items():
            if (
                status == ToolStatus.disabled
                or tool_name in server.disabled_tools
                or tool_name in disabled_tools.get(str(server.id), [])
            ):
                continue
            base_name = sanitize_tool_name(f"{server.name}_{tool_name}")
            candidate = base_name
            suffix = 1
            while candidate in used_names:
                suffix += 1
                suffix_text = f"_{suffix}"
                truncated = base_name[: 128 - len(suffix_text)].rstrip("_") or "tool"
                candidate = f"{truncated}{suffix_text}"
            used_names.add(candidate)
            owners[candidate] = server.id
    return owners


def _public_tool_icon(
    server: MCPServerDB, image: MCPServerImageDB | None
) -> str | None:
    if image is not None and image.media_type.startswith("image/"):
        encoded = base64.b64encode(image.data).decode("ascii")
        return f"data:{image.media_type};base64,{encoded}"
    if server.icon_url and server.icon_url.startswith(("https://", "http://")):
        return server.icon_url
    return None


def _referenced_artifact_ids(messages: list[Any]) -> list[UUID]:
    found: dict[UUID, None] = {}
    for message in messages:
        kwargs = getattr(message, "additional_kwargs", {}) or {}
        attachments = kwargs.get("attachments")
        if isinstance(attachments, list):
            for item in attachments:
                value = item if isinstance(item, str) else None
                if isinstance(item, dict):
                    value = item.get("id")
                try:
                    if isinstance(value, str):
                        found[UUID(value)] = None
                except ValueError:
                    continue

        artifact = getattr(message, "artifact", None)
        descriptors = (
            artifact.get("auxilia_artifacts") if isinstance(artifact, dict) else None
        )
        if isinstance(descriptors, list):
            for descriptor in descriptors:
                value = descriptor.get("id") if isinstance(descriptor, dict) else None
                try:
                    if isinstance(value, str):
                        found[UUID(value)] = None
                except ValueError:
                    continue
        gallery = public_image_gallery(artifact)
        if gallery is not None:
            for image in gallery["images"]:
                found[UUID(image["id"])] = None
    return list(found)


def _share_response(share: ConversationShareDB) -> ConversationShareResponse:
    return ConversationShareResponse(
        id=share.id,
        thread_id=share.thread_id,
        token=_share_token(share.id),
        created_at=share.created_at,
    )


class ConversationShareService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repository = ConversationShareRepository(db)

    async def _snapshot_tool_servers(
        self,
        workspace_id: UUID,
        thread: ThreadDB,
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        used_tool_names = _used_tool_names(messages)
        if not used_tool_names:
            return []
        spec = await AgentRepository(self.db, workspace_id).get_run_spec(
            thread.agent_id
        )
        if spec is None:
            return []
        force_enable_resources = (
            thread.tool_mode.force_enable_all_capabilities
            if thread.tool_mode is not None
            else spec.agent.tool_discovery_mode is ToolDiscoveryMode.lazy
        )
        disabled_server_ids = (
            set() if force_enable_resources else set(thread.disabled_mcp_server_ids)
        )
        disabled_subagent_ids = (
            set() if force_enable_resources else set(thread.disabled_subagent_ids)
        )
        active_agent_specs = [
            spec.agent,
            *(
                subagent
                for subagent in spec.subagents
                if str(subagent.id) not in disabled_subagent_ids
            ),
        ]
        active_bindings = [
            binding
            for agent_spec in active_agent_specs
            for binding in agent_spec.mcp_servers
            if str(binding.mcp_server_id) not in disabled_server_ids
        ]
        server_ids = {binding.mcp_server_id for binding in active_bindings}
        mcp_servers = MCPServerRepository(self.db, workspace_id)
        servers = await mcp_servers.list_by_ids(server_ids)
        servers_by_id = {server.id: server for server in servers}
        runtime_name_owners: dict[str, set[UUID]] = {}
        for agent_spec in active_agent_specs:
            for tool_name, server_id in _runtime_tool_owners(
                [
                    binding
                    for binding in agent_spec.mcp_servers
                    if str(binding.mcp_server_id) not in disabled_server_ids
                ],
                servers_by_id,
                thread.disabled_mcp_tools,
            ).items():
                runtime_name_owners.setdefault(tool_name, set()).add(server_id)
        matched_names_by_server: dict[UUID, list[str]] = {}
        for tool_name in used_tool_names:
            owner_ids = runtime_name_owners.get(tool_name, set())
            if len(owner_ids) == 1:
                server_id = next(iter(owner_ids))
                matched_names_by_server.setdefault(server_id, []).append(tool_name)
        used_server_ids = set(matched_names_by_server)
        used_servers = [server for server in servers if server.id in used_server_ids]
        server_images = await mcp_servers.images_by_server_ids(
            [server.id for server in used_servers]
        )
        return [
            {
                "name": server.name,
                "icon_url": _public_tool_icon(server, server_images.get(server.id)),
                "tool_names": sorted(matched_names_by_server[server.id]),
            }
            for server in sorted(used_servers, key=lambda item: item.name.casefold())
        ]

    async def _owned_thread(self, workspace_id: UUID, thread_id: str, user_id: UUID):
        thread = await ThreadRepository(self.db, workspace_id).get(thread_id)
        if thread is None:
            raise NotFoundError("Thread not found")
        if thread.user_id != user_id:
            raise PermissionDeniedError("Only the thread owner can publish it")
        return thread

    async def get(
        self, workspace_id: UUID, thread_id: str, user_id: UUID
    ) -> ConversationShareResponse | None:
        await self._owned_thread(workspace_id, thread_id, user_id)
        share = await self.repository.get_for_thread(workspace_id, thread_id)
        return _share_response(share) if share else None

    async def create(
        self, workspace_id: UUID, thread_id: str, user_id: UUID
    ) -> ConversationShareResponse:
        thread = await self._owned_thread(workspace_id, thread_id, user_id)
        runs = RunRepository(self.db, workspace_id)
        await runs.lock_thread_runs(thread_id)
        existing = await self.repository.get_for_thread(workspace_id, thread_id)
        if existing is not None:
            return _share_response(existing)
        locked_thread = await ThreadRepository(self.db, workspace_id).lock(thread_id)
        if locked_thread is None:
            raise NotFoundError("Thread not found")
        thread = locked_thread
        if await runs.get_active_for_thread(thread_id) is not None:
            raise DomainValidationError(
                "Wait for the conversation to finish before publishing it"
            )
        internal_thread_id = checkpoint_thread_id(workspace_id, thread_id)
        async with get_checkpointer() as checkpointer:
            state = await get_checkpoint_state(checkpointer, internal_thread_id)
        if state.saved is None or not state.messages:
            raise DomainValidationError("This conversation has no messages to publish")
        if pending_interrupt(state) is not None:
            raise DomainValidationError(
                "Resolve the pending approval before publishing this conversation"
            )
        visible_messages: list[Any] = []
        public_messages: list[dict[str, Any]] = []
        for message in state.messages:
            serialized = serialize_public_message(message)
            if serialized is not None:
                visible_messages.append(message)
                public_messages.append(serialized)
        if not visible_messages:
            raise DomainValidationError(
                "This conversation has no visible messages to publish"
            )
        checkpoint_id = str(state.saved.checkpoint["id"])
        agent = await AgentRepository(self.db, workspace_id).get_scoped(thread.agent_id)
        if agent is None:
            raise NotFoundError("Agent not found")
        catalog = {model.model_id: model for model in await get_whitelist()}
        catalog_model = catalog.get(thread.model_id) if thread.model_id else None
        try:
            conversation_cost = await CostService(self.db).conversation(
                workspace_id,
                thread_id,
                thread.model_id,
                catalog=catalog,
            )
            cost = {
                "known_cost": str(conversation_cost.known_cost),
                "complete": conversation_cost.complete,
                "call_count": conversation_cost.call_count,
                "unpriced_call_count": conversation_cost.unpriced_call_count,
                "total_tokens": conversation_cost.usage_details.total,
                "usage_details": conversation_cost.usage_details.model_dump(),
                "cost_details": {
                    name: str(value)
                    for name, value in conversation_cost.cost_details.model_dump().items()
                },
            }
        except Exception:  # noqa: BLE001 — optional metadata must not block sharing
            logger.warning(
                "Could not snapshot cost for shared thread %s",
                thread_id,
                exc_info=True,
            )
            cost = None
        run_snapshots = [
            RunResponse.from_record(run).model_dump(mode="json")
            for run in await runs.list_for_thread(thread_id)
        ]
        share = await self.repository.create(
            ConversationShareCreateDB(
                workspace_id=workspace_id,
                thread_id=thread_id,
                created_by_id=user_id,
                checkpoint_id=checkpoint_id,
                title=thread.first_message_content,
                agent_name=agent.name,
                agent_emoji=agent.emoji,
                agent_color=agent.color,
                model_id=thread.model_id,
                model_name=(
                    catalog_model.display_name
                    if catalog_model is not None
                    else thread.model_id
                ),
                memories_enabled=thread.memories_enabled,
                cost=cost,
                runs=run_snapshots,
                tool_servers=await self._snapshot_tool_servers(
                    workspace_id, thread, public_messages
                ),
            )
        )

        artifact_ids = _referenced_artifact_ids(visible_messages)
        artifacts = await ArtifactRepository(self.db, workspace_id).by_ids(
            thread.id, artifact_ids
        )
        await self.repository.add_artifacts(
            [
                ConversationShareArtifactDB(
                    share_id=share.id,
                    artifact_id=row.id,
                    sha256=row.sha256,
                    origin=row.origin,
                    tool_call_id=row.tool_call_id,
                    title=row.title,
                    filename=row.filename,
                    mime_type=row.mime_type,
                    size=row.size,
                )
                for row in artifacts
            ]
        )
        return _share_response(share)

    async def delete(self, workspace_id: UUID, thread_id: str, user_id: UUID) -> None:
        await self._owned_thread(workspace_id, thread_id, user_id)
        share = await self.repository.get_for_thread(workspace_id, thread_id)
        if share is not None:
            await self.repository.delete(share)

    async def _resolve(self, share_id: UUID, token: str):
        row = await self.repository.public_details(share_id)
        if row is None or not hmac.compare_digest(token, _share_token(share_id)):
            raise NotFoundError("Public conversation not found")
        return row

    async def public_snapshot(
        self, share_id: UUID, token: str
    ) -> PublicConversationResponse:
        share = await self._resolve(share_id, token)
        internal_thread_id = checkpoint_thread_id(share.workspace_id, share.thread_id)
        async with get_checkpointer() as checkpointer:
            state = await get_checkpoint_state(
                checkpointer,
                internal_thread_id,
                checkpoint_id=share.checkpoint_id,
            )
        if state.saved is None:
            raise NotFoundError("Public conversation is no longer available")
        messages = [
            serialized
            for message in state.messages
            if (serialized := serialize_public_message(message)) is not None
        ]
        artifacts = await self.repository.list_artifacts(share.id)
        return PublicConversationResponse(
            id=share.id,
            title=share.title,
            published_at=share.created_at,
            agent=PublicAgent(
                name=share.agent_name,
                emoji=share.agent_emoji,
                color=share.agent_color,
            ),
            model_id=share.model_id,
            model_name=share.model_name,
            memories_enabled=share.memories_enabled,
            cost=share.cost,
            runs=share.runs,
            messages=messages,
            artifacts=[
                PublicArtifact(
                    id=item.artifact_id,
                    tool_call_id=item.tool_call_id,
                    title=item.title,
                    filename=item.filename,
                    mime_type=item.mime_type,
                    size=item.size,
                )
                for item in artifacts
            ],
            tool_servers=[
                PublicToolServer.model_validate(server) for server in share.tool_servers
            ],
        )

    async def public_artifact(
        self, share_id: UUID, artifact_id: UUID, token: str
    ) -> tuple[ArtifactDB, bytes]:
        share = await self._resolve(share_id, token)
        entry = await self.repository.artifact(share.id, artifact_id)
        if entry is None:
            raise NotFoundError("Shared file not found")
        snapshot, current = entry
        if (
            current.workspace_id != share.workspace_id
            or current.thread_id != share.thread_id
        ):
            raise NotFoundError("Shared file not found")
        if not hmac.compare_digest(snapshot.sha256, current.sha256):
            raise ArtifactGoneError("This shared file has changed since publication")
        return await ArtifactService(self.db, share.workspace_id).content(
            share.thread_id, artifact_id
        )


def get_conversation_share_service(
    db: AsyncSession = Depends(get_db),
) -> ConversationShareService:
    return ConversationShareService(db)
