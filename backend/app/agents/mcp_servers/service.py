import logging
from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.core.repository import AgentRepository
from app.agents.mcp_servers.repository import AgentMCPServerRepository
from app.agents.models import AgentDB, AgentMCPServerBase, AgentMCPServerDB
from app.agents.schemas import (
    AgentMCPServerConfig,
    AgentMCPServerCreate,
    AgentMCPServerPatch,
)
from app.database import get_db
from app.exceptions import DomainValidationError, NotFoundError
from app.mcp.client.connectivity import connect_to_server, is_authorized
from app.mcp.servers.models import MCPAuthType, MCPServerDB
from app.mcp.servers.repository import MCPServerRepository
from app.mcp.servers.schemas import MCPServerAgentResponse
from app.service import BaseService
from app.visibility import (
    ResourceVisibility,
    audience_contains,
    is_resource_visible_to_identity,
)
from app.workspaces.dependencies import get_active_workspace_id
from app.workspaces.models import WorkspaceRole
from app.workspaces.repository import WorkspaceRepository


logger = logging.getLogger(__name__)


class AgentMCPServerService(BaseService[AgentMCPServerDB, AgentMCPServerRepository]):
    not_found_message = "Agent MCP server not found"

    def __init__(self, db: AsyncSession, workspace_id: UUID | None = None):
        super().__init__(db, AgentMCPServerRepository(db))
        self.workspace_id = workspace_id
        self._servers = MCPServerRepository(db, workspace_id)
        self._agents = AgentRepository(db, workspace_id)
        self._workspaces = WorkspaceRepository(db)

    async def _ensure_agent(self, agent_id: UUID) -> None:
        if await self._agents.get_scoped(agent_id) is None:
            raise NotFoundError("Agent not found")

    async def _ensure_agent_for_update(self, agent_id: UUID) -> None:
        if await self._agents.get_scoped_for_update(agent_id) is None:
            raise NotFoundError("Agent not found")

    async def _ensure_server(self, server_id: UUID) -> MCPServerDB:
        server = await self._servers.get_scoped(server_id)
        if not server:
            raise NotFoundError("MCP server not found")
        return server

    async def _ensure_server_for_update(self, server_id: UUID) -> MCPServerDB:
        server = await self._servers.get_scoped_for_update(server_id)
        if server is None:
            raise NotFoundError("MCP server not found")
        return server

    async def _ensure_scope_compatible(
        self, agent_id: UUID, server: MCPServerDB
    ) -> None:
        agent = await self._agents.get_scoped(agent_id)
        if agent is None:
            raise NotFoundError("Agent not found")
        agent_visibility = (
            agent.visibility
            if isinstance(agent.visibility, ResourceVisibility)
            else ResourceVisibility.personal
        )
        server_visibility = (
            server.visibility
            if isinstance(server.visibility, ResourceVisibility)
            else ResourceVisibility.workspace
        )
        if not audience_contains(
            parent_visibility=agent_visibility,
            parent_owner_id=agent.owner_id,
            parent_team_ids=(
                set(await self._agents.get_team_ids(agent.id))
                if agent_visibility == ResourceVisibility.teams
                else set()
            ),
            child_visibility=server_visibility,
            child_owner_id=server.owner_id,
            child_team_ids=(
                set(await self._servers.list_team_ids(server.id))
                if server_visibility == ResourceVisibility.teams
                else set()
            ),
        ):
            raise DomainValidationError(
                f"MCP server '{server.name}' is more private than this agent"
            )
        child_team_ids = (
            set(await self._servers.list_team_ids(server.id))
            if server_visibility == ResourceVisibility.teams
            else set()
        )
        if self.workspace_id is None or not isinstance(agent, AgentDB):
            return
        for grant in await self._agents.get_permissions(agent.id):
            membership = await self._workspaces.get_membership(
                self.workspace_id, grant.user_id
            )
            if membership is not None and not is_resource_visible_to_identity(
                visibility=server_visibility,
                owner_id=server.owner_id,
                team_ids=child_team_ids,
                user_id=grant.user_id,
                is_admin=membership.role == WorkspaceRole.admin,
                team_id=membership.team_id,
            ):
                raise DomainValidationError(
                    f"MCP server '{server.name}' is not visible to every agent grantee"
                )

    async def _sync_tools(
        self,
        db_link: AgentMCPServerDB,
        mcp_server: MCPServerDB,
        user_id: str,
    ) -> None:
        try:
            async with connect_to_server(
                mcp_server, user_id, self.workspace_id, self.db
            ) as client:
                fetched_names = [tool.name for tool in await client.list_tools()]
            # The fetch can take seconds, so a concurrent save may have
            # rewritten the map meanwhile. Reload the row under a lock and
            # merge against the fresh state — otherwise this assignment
            # would silently revert that save (lost update).
            await self.db.refresh(db_link, with_for_update=True)
            # Merge, don't clobber: the server's tool list is the key
            # universe, but a curated status survives a re-sync.
            existing = db_link.tools or {}
            db_link.tools = {
                name: existing.get(name, "always_allow") for name in fetched_names
            }
            self.db.add(db_link)
            await self.db.flush()
            await self.db.refresh(db_link)
        except Exception as e:  # noqa: BLE001 — FIXME(P3-12): an explicit sync that fails still reports success
            logger.warning(f"Failed to fetch tools for MCP server {mcp_server.id}: {e}")

    async def create_or_update(
        self,
        agent_id: UUID,
        server_id: UUID,
        data: AgentMCPServerCreate,
        user_id: str,
    ) -> AgentMCPServerDB:
        await self._ensure_agent_for_update(agent_id)
        mcp_server = await self._ensure_server_for_update(server_id)
        await self._ensure_scope_compatible(agent_id, mcp_server)

        existing = await self.repository.get(agent_id, server_id)
        if existing:
            if data.tools is not None:
                existing.tools = data.tools
                self.db.add(existing)
                await self.db.flush()
                await self.db.refresh(existing)
            return existing

        db_link = await self.repository.create(
            AgentMCPServerBase(
                agent_id=agent_id,
                mcp_server_id=server_id,
                tools=None,
            )
        )

        should_fetch = mcp_server.auth_type in (
            MCPAuthType.none,
            MCPAuthType.api_key,
            MCPAuthType.service_identity,
        ) or (
            mcp_server.auth_type == MCPAuthType.oauth2
            and await is_authorized(
                mcp_server, user_id, self.workspace_id, refresh=False
            )
        )
        if should_fetch:
            await self._sync_tools(db_link, mcp_server, user_id)

        return db_link

    async def update(
        self, agent_id: UUID, server_id: UUID, data: AgentMCPServerPatch
    ) -> AgentMCPServerDB:
        await self._ensure_agent_for_update(agent_id)
        await self._ensure_server_for_update(server_id)
        link = await self.repository.get(agent_id, server_id)
        if not link:
            raise NotFoundError(self.not_found_message)

        if data.tools is not None:
            existing_tools = link.tools or {}
            data = AgentMCPServerPatch(tools={**existing_tools, **data.tools})

        return await self.repository.update(link, data)

    async def set_for_agent(
        self, agent_id: UUID, configs: list[AgentMCPServerConfig]
    ) -> None:
        """Whole-set replace of an agent's MCP bindings: upsert the wanted
        links and delete the rest. `tools` is written exactly as provided —
        the caller owns the complete map, so no discovery and no merge."""
        await self._ensure_agent_for_update(agent_id)
        existing = await self.repository.list_for_agent(agent_id)
        by_server = {link.mcp_server_id: link for link in existing}
        wanted = {config.mcp_server_id for config in configs}

        for config in sorted(configs, key=lambda item: str(item.mcp_server_id)):
            server = await self._ensure_server_for_update(config.mcp_server_id)
            await self._ensure_scope_compatible(agent_id, server)
            link = by_server.get(config.mcp_server_id)
            if link:
                if link.tools != config.tools:
                    link.tools = config.tools
                    self.db.add(link)
            else:
                await self.repository.create(
                    AgentMCPServerBase(
                        agent_id=agent_id,
                        mcp_server_id=config.mcp_server_id,
                        tools=config.tools,
                    )
                )
        for server_id, link in by_server.items():
            if server_id not in wanted:
                await self.repository.delete(link)
        await self.db.flush()

    async def delete(self, agent_id: UUID, server_id: UUID) -> None:
        await self._ensure_agent_for_update(agent_id)
        await self._ensure_server_for_update(server_id)
        link = await self.repository.get(agent_id, server_id)
        if not link:
            raise NotFoundError(self.not_found_message)
        await self.repository.delete(link)

    async def sync_tools(
        self, agent_id: UUID, server_id: UUID, user_id: str
    ) -> AgentMCPServerDB:
        await self._ensure_agent(agent_id)
        mcp_server = await self._ensure_server(server_id)
        link = await self.repository.get(agent_id, server_id)
        if not link:
            raise NotFoundError(self.not_found_message)
        await self._sync_tools(link, mcp_server, user_id)
        return link

    # -- Server-side views ---------------------------------------------------
    #
    # A binding references a server, so the dependency runs agents → mcp and
    # the MCP-server module never reaches back in here. Its router composes:
    # `DELETE /mcp-servers/{id}` detaches through this service, then deletes
    # through `MCPServerService` (#369).

    async def list_agents_for_server(
        self, server_id: UUID
    ) -> list[MCPServerAgentResponse]:
        """Agents currently bound to the server (delete-guard dialog)."""
        await self._ensure_server(server_id)
        agents = await self.repository.list_agents_for_server(server_id)
        return [
            MCPServerAgentResponse(
                id=agent.id,
                name=agent.name,
                emoji=agent.emoji,
                color=agent.color,
                image_revision=agent.image_revision,
            )
            for agent in agents
        ]

    async def detach_server(self, server_id: UUID) -> None:
        """Drop the server's binding from every agent — the dialog's explicit
        confirm before the server itself is deleted."""
        await self._ensure_server_for_update(server_id)
        await self.repository.delete_all_for_server(server_id)


def get_agent_mcp_server_service(
    db: AsyncSession = Depends(get_db),
    workspace_id: UUID = Depends(get_active_workspace_id),
) -> AgentMCPServerService:
    return AgentMCPServerService(db, workspace_id)
