from __future__ import annotations

import logging
from collections import defaultdict
from uuid import UUID

from fastapi import Depends
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.agents.core.repository import AgentRepository
from app.agents.mcp_servers.repository import AgentMCPServerRepository
from app.agents.mcp_servers.service import AgentMCPServerService
from app.agents.models import (
    AgentDB,
    AgentUserPermissionDB,
)
from app.agents.schemas import (
    AgentConfig,
    AgentCreateDB,
    AgentMCPServerResponse,
    AgentOwnerInfo,
    AgentPatch,
    AgentPermissionCreate,
    AgentResponse,
    TagInfo,
)
from app.agents.subagents.service import SubagentService
from app.database import get_db
from app.exceptions import NotFoundError, PermissionDeniedError
from app.mcp.client.connectivity import is_authorized
from app.mcp.servers.models import MCPServerDB
from app.service import BaseService
from app.tags.service import TagService
from app.threads.service import ThreadService
from app.users.models import WorkspaceRole
from app.users.service import UserService


logger = logging.getLogger(__name__)


class AgentService(BaseService[AgentDB, AgentRepository]):
    not_found_message = "Agent not found"

    def __init__(self, db: AsyncSession):
        super().__init__(db, AgentRepository(db))
        self.subagent_service = SubagentService(db)
        self.thread_service = ThreadService(db)
        self.tag_service = TagService(db)
        self.user_service = UserService(db)
        self.mcp_server_repository = AgentMCPServerRepository(db)
        self.mcp_server_service = AgentMCPServerService(db)

    @staticmethod
    def _resolve_permission(
        agent: AgentDB,
        user_id: UUID | None,
        user_role: WorkspaceRole | None,
        granted: dict[UUID, str],
        team_agent_ids: set[UUID] | None = None,
    ) -> str | None:
        if user_id and agent.owner_id == user_id:
            return "owner"
        if user_role == WorkspaceRole.admin:
            return "admin"
        explicit = granted.get(agent.id)
        if explicit:
            return explicit
        if team_agent_ids and agent.id in team_agent_ids:
            return "member"
        return None

    async def _assemble(
        self,
        agents: list[AgentDB],
        mcp_map: dict[UUID, list[AgentMCPServerResponse]],
        permissions_map: dict[UUID, str],
        user_id: UUID | None,
        user_role: WorkspaceRole | None,
        team_agent_ids: set[UUID] | None = None,
    ) -> list[AgentResponse]:
        agent_ids = [a.id for a in agents]
        (
            subagents_map,
            is_subagent_ids,
        ) = await self.subagent_service.list_all_subagent_data(agent_ids)
        tag_ids = list({a.tag_id for a in agents if a.tag_id is not None})
        tags_by_id = {t.id: t for t in await self.tag_service.list_by_ids(tag_ids)}
        owner_ids = list({a.owner_id for a in agents})
        owners_by_id = {u.id: u for u in await self.user_service.list_by_ids(owner_ids)}
        return [
            AgentResponse(
                **agent.model_dump(),
                mcp_servers=mcp_map.get(agent.id, []),
                subagents=subagents_map.get(agent.id, []),
                tag=(
                    TagInfo(id=tag.id, name=tag.name)
                    if (tag := tags_by_id.get(agent.tag_id)) is not None
                    else None
                ),
                owner=(
                    AgentOwnerInfo(id=owner.id, name=owner.name, email=owner.email)
                    if (owner := owners_by_id.get(agent.owner_id)) is not None
                    else None
                ),
                is_subagent=agent.id in is_subagent_ids,
                current_user_permission=self._resolve_permission(
                    agent, user_id, user_role, permissions_map, team_agent_ids
                ),
            )
            for agent in agents
        ]

    @staticmethod
    def _group_rows(
        rows: list,
        user_id: UUID | None,
    ) -> tuple[
        dict[UUID, AgentDB],
        dict[UUID, list[AgentMCPServerResponse]],
        dict[UUID, str],
        set[UUID],
    ]:
        agents_map: dict[UUID, AgentDB] = {}
        mcp_map: dict[UUID, list[AgentMCPServerResponse]] = defaultdict(list)
        permissions_map: dict[UUID, str] = {}
        team_agent_ids: set[UUID] = set()
        for row in rows:
            agent = row[0]
            link = row[1]
            agents_map[agent.id] = agent
            if link is not None:
                mcp_map[agent.id].append(AgentMCPServerResponse.model_validate(link))
            if user_id and len(row) > 2:
                permission = row[2]
                if permission and agent.id not in permissions_map:
                    permissions_map[agent.id] = permission.value
            if user_id and len(row) > 3 and row[3] is not None:
                team_agent_ids.add(agent.id)
        return agents_map, mcp_map, permissions_map, team_agent_ids

    async def create(self, data: AgentCreateDB) -> AgentDB:
        return await self.repository.create(data)

    async def create_from_config(
        self,
        config: AgentConfig,
        *,
        owner_id: UUID,
        user_role: WorkspaceRole | None = None,
        user_team_id: UUID | None = None,
    ) -> AgentResponse:
        """Create an agent from a full config document in one transaction —
        the create-mode counterpart of `set_config`. Nothing persists if any
        binding is invalid, so a failed draft never leaves a stray agent."""
        agent = await self.repository.create(
            AgentCreateDB(
                name=config.name,
                instructions=config.instructions,
                owner_id=owner_id,
                emoji=config.emoji,
                color=config.color,
                description=config.description,
                has_code_interpreter=config.has_code_interpreter,
            )
        )
        await self.mcp_server_service.set_for_agent(agent.id, config.mcp_servers)
        await self.subagent_service.set_for_supervisor(
            agent.id, config.subagent_ids, user_role=user_role
        )
        return await self.get(
            agent.id, user_id=owner_id, user_role=user_role, user_team_id=user_team_id
        )

    async def get(
        self,
        agent_id: UUID,
        user_id: UUID | None = None,
        user_role: WorkspaceRole | None = None,
        user_team_id: UUID | None = None,
        include_archived: bool = False,
    ) -> AgentResponse:
        rows = await self.repository.list_with_permissions(
            user_id=user_id,
            user_role=user_role,
            user_team_id=user_team_id,
            agent_id=agent_id,
            include_archived=include_archived,
        )
        if not rows:
            raise NotFoundError(self.not_found_message)

        agents_map, mcp_map, permissions_map, team_agent_ids = self._group_rows(
            rows, user_id
        )
        responses = await self._assemble(
            list(agents_map.values()),
            mcp_map,
            permissions_map,
            user_id,
            user_role,
            team_agent_ids,
        )
        return responses[0]

    async def list(
        self,
        user_id: UUID | None = None,
        user_role: WorkspaceRole | None = None,
        user_team_id: UUID | None = None,
        archived: bool = False,
    ) -> list[AgentResponse]:
        rows = await self.repository.list_with_permissions(
            user_id=user_id,
            user_role=user_role,
            user_team_id=user_team_id,
            archived_only=archived,
        )
        agents_map, mcp_map, permissions_map, team_agent_ids = self._group_rows(
            rows, user_id
        )
        return await self._assemble(
            list(agents_map.values()),
            mcp_map,
            permissions_map,
            user_id,
            user_role,
            team_agent_ids,
        )

    async def update(
        self,
        agent_id: UUID,
        data: AgentPatch,
        user_id: UUID | None = None,
        user_role: WorkspaceRole | None = None,
        user_team_id: UUID | None = None,
    ) -> AgentResponse:
        existing = await self.get(
            agent_id, user_id=user_id, user_role=user_role, user_team_id=user_team_id
        )
        if existing.current_user_permission not in ("owner", "admin", "editor"):
            raise PermissionDeniedError("Not authorized to edit this agent")
        if data.tag_id is not None:
            await self.tag_service.get(data.tag_id)
        agent = await self.get_or_404(agent_id)
        try:
            await self.repository.update(agent, data)
        except IntegrityError as exc:
            if "fk_agents_tag_id_tags" not in str(getattr(exc, "orig", exc)):
                raise
            # The tag existed at validation time but was deleted before the
            # flush — surface the same 404 the validation would have raised.
            raise NotFoundError("Tag not found") from exc
        return await self.get(
            agent_id, user_id=user_id, user_role=user_role, user_team_id=user_team_id
        )

    async def set_config(
        self,
        agent_id: UUID,
        config: AgentConfig,
        user_id: UUID,
        user_role: WorkspaceRole | None = None,
        user_team_id: UUID | None = None,
    ) -> AgentResponse:
        """Atomic whole-config replace: scalars, MCP bindings and subagents in
        one request transaction. Performs zero network calls — the client
        already carries the complete per-tool maps (or None = never synced)."""
        existing = await self.get(
            agent_id, user_id=user_id, user_role=user_role, user_team_id=user_team_id
        )
        if existing.current_user_permission not in ("owner", "admin", "editor"):
            raise PermissionDeniedError("Not authorized to edit this agent")

        agent = await self.get_or_404(agent_id)
        await self.repository.update(
            agent,
            AgentPatch(
                name=config.name,
                instructions=config.instructions,
                description=config.description,
                emoji=config.emoji,
                color=config.color,
                has_code_interpreter=config.has_code_interpreter,
            ),
        )
        await self.mcp_server_service.set_for_agent(agent_id, config.mcp_servers)
        await self.subagent_service.set_for_supervisor(
            agent_id, config.subagent_ids, user_role=user_role
        )
        return await self.get(
            agent_id, user_id=user_id, user_role=user_role, user_team_id=user_team_id
        )

    async def delete(
        self,
        agent_id: UUID,
        user_id: UUID | None = None,
        user_role: WorkspaceRole | None = None,
    ) -> None:
        agent = await self.get_or_404(agent_id)
        if agent.owner_id != user_id and user_role != WorkspaceRole.admin:
            raise PermissionDeniedError("Not authorized to delete this agent")
        await self.subagent_service.delete_all_for_agent(agent_id)
        await self.repository.archive(agent)

    async def restore(
        self,
        agent_id: UUID,
        user_id: UUID | None = None,
        user_role: WorkspaceRole | None = None,
        user_team_id: UUID | None = None,
    ) -> AgentResponse:
        existing = await self.get(
            agent_id,
            user_id=user_id,
            user_role=user_role,
            user_team_id=user_team_id,
            include_archived=True,
        )
        if existing.current_user_permission not in ("owner", "admin"):
            raise PermissionDeniedError("Not authorized to restore this agent")
        agent = await self.get_or_404(agent_id)
        await self.repository.restore(agent)
        return await self.get(
            agent_id,
            user_id=user_id,
            user_role=user_role,
            user_team_id=user_team_id,
            include_archived=True,
        )

    async def delete_permanently(
        self,
        agent_id: UUID,
        user_id: UUID | None = None,
        user_role: WorkspaceRole | None = None,
        user_team_id: UUID | None = None,
    ) -> None:
        existing = await self.get(
            agent_id,
            user_id=user_id,
            user_role=user_role,
            user_team_id=user_team_id,
            include_archived=True,
        )
        if existing.current_user_permission not in ("owner", "admin"):
            raise PermissionDeniedError(
                "Not authorized to permanently delete this agent"
            )
        agent = await self.get_or_404(agent_id)
        # Delete every DB row that references the agent first (threads must go
        # before the agent row due to the FK), then purge checkpoints last.
        thread_ids = await self.thread_service.delete_rows_for_agent(agent_id)
        await self.subagent_service.delete_all_for_agent(agent_id)
        await self.mcp_server_repository.delete_all_for_agent(agent_id)
        await self.repository.delete_all_permissions(agent_id)
        await self.repository.delete_all_teams(agent_id)
        await self.repository.delete(agent)
        # Checkpoints live on a separate auto-committed connection and can't be
        # rolled back, so purge them only after all DB deletes have succeeded.
        await self.thread_service.purge_checkpoints(thread_ids)

    async def get_permissions(self, agent_id: UUID) -> list[AgentUserPermissionDB]:
        return await self.repository.get_permissions(agent_id)

    async def set_permissions(
        self, agent_id: UUID, permissions: list[AgentPermissionCreate]
    ) -> list[AgentUserPermissionDB]:
        return await self.repository.set_permissions(agent_id, permissions)

    async def get_team_ids(self, agent_id: UUID) -> list[UUID]:
        return await self.repository.get_team_ids(agent_id)

    async def set_teams(self, agent_id: UUID, team_ids: list[UUID]) -> list[UUID]:
        return await self.repository.set_teams(agent_id, team_ids)

    async def collect_run_bindings(
        self, agent_id: UUID
    ) -> list[AgentMCPServerResponse]:
        """Every MCP binding a run of this agent touches: the agent's own plus
        each direct subagent's. One level only — matches `Agent.build`, which
        does not recurse into a subagent's own subagents.

        NOT deduped: `tools` (configuration state) is per binding, so a server
        configured on the parent but left unconfigured on a subagent must stay
        visible to the readiness check. Callers doing per-server work (the OAuth
        probe) dedupe by mcp_server_id themselves."""
        agent = await self.get(agent_id, include_archived=True)
        bindings: list[AgentMCPServerResponse] = list(agent.mcp_servers or [])
        for sub in agent.subagents or []:
            sub_agent = await self.get(sub.id, include_archived=True)
            bindings.extend(sub_agent.mcp_servers or [])
        return bindings

    async def describe_readiness(self, agent_id: UUID, user_id: str) -> dict:
        # Includes subagents' servers: a subagent's unauthorized OAuth server
        # must keep the agent "not ready" too, or the run launches and fails
        # mid-flight when the subagent calls it.
        bindings = await self.collect_run_bindings(agent_id)

        if not bindings:
            return {"ready": True, "disconnected_servers": [], "status": "ready"}

        for binding in bindings:
            if binding.tools is None:
                return {
                    "ready": False,
                    "disconnected_servers": [],
                    "status": "not_configured",
                }

        server_ids = {b.mcp_server_id for b in bindings}  # dedupe for the probe
        stmt = select(MCPServerDB).where(MCPServerDB.id.in_(server_ids))
        result = await self.db.execute(stmt)
        servers = list(result.scalars().all())

        disconnected: list[str] = []
        for server in servers:
            if not await is_authorized(server, user_id):
                disconnected.append(str(server.id))

        return {
            "ready": len(disconnected) == 0,
            "disconnected_servers": disconnected,
            "status": "disconnected",
        }


def get_agent_service(db: AsyncSession = Depends(get_db)) -> AgentService:
    return AgentService(db)
