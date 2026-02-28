from collections import defaultdict
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.agents.models import (
    AgentDB,
    AgentMCPServer,
    AgentMCPServerBindingDB,
    AgentRead,
    AgentUserPermissionDB,
)
from app.users.models import WorkspaceRole


async def read_agents(
    db: AsyncSession,
    user_id: UUID | None = None,
    user_role: WorkspaceRole | None = None,
) -> list[AgentRead]:
    is_workspace_admin = user_role == WorkspaceRole.admin

    if user_id and not is_workspace_admin:
        query = (
            select(AgentDB, AgentMCPServerBindingDB, AgentUserPermissionDB.permission)
            .outerjoin(
                AgentMCPServerBindingDB, AgentDB.id == AgentMCPServerBindingDB.agent_id
            )
            .outerjoin(
                AgentUserPermissionDB,
                (AgentDB.id == AgentUserPermissionDB.agent_id)
                & (AgentUserPermissionDB.user_id == user_id),
            )
            .order_by(AgentDB.created_at.asc())
        )
    else:
        query = (
            select(AgentDB, AgentMCPServerBindingDB)
            .outerjoin(
                AgentMCPServerBindingDB, AgentDB.id == AgentMCPServerBindingDB.agent_id
            )
            .order_by(AgentDB.created_at.asc())
        )
        .where(AgentDB.is_archived == False)
        .order_by(AgentDB.created_at.asc())
    )
    if owner_id:
        query = query.where(AgentDB.owner_id == owner_id)

    result = await db.execute(query)
    rows = result.all()

    agents_map: dict[UUID, AgentDB] = {}
    bindings_map: dict[UUID, list[AgentMCPServer]] = defaultdict(list)
    permissions_map: dict[UUID, str] = {}

    for row in rows:
        agent = row[0]
        binding = row[1]
        agents_map[agent.id] = agent

        if binding is not None:
            bindings_map[agent.id].append(
                AgentMCPServer(id=binding.mcp_server_id, tools=binding.tools)
            )

        if user_id and agent.owner_id == user_id:
            permissions_map[agent.id] = "owner"
        elif is_workspace_admin:
            permissions_map[agent.id] = "admin"
        elif user_id:
            permission = row[2]
            if permission and agent.id not in permissions_map:
                permissions_map[agent.id] = permission.value

    return [
        AgentRead(
            **agent.model_dump(),
            mcp_servers=bindings_map.get(agent.id, []),
            current_user_permission=permissions_map.get(agent.id),
        )
        for agent in agents_map.values()
    ]


async def read_agent(
    agent_id: UUID,
    db: AsyncSession,
    user_id: UUID | None = None,
    user_role: WorkspaceRole | None = None,
) -> AgentRead:
    result = await db.execute(
        select(AgentDB, AgentMCPServerBindingDB)
        .outerjoin(
            AgentMCPServerBindingDB, AgentDB.id == AgentMCPServerBindingDB.agent_id
        )
        .where(AgentDB.id == agent_id)
    )
    rows = result.all()

    if not rows:
        raise HTTPException(status_code=404, detail="Agent not found")

    agent = rows[0][0]

    mcp_servers = [
        AgentMCPServer(
            id=binding.mcp_server_id,
            tools=binding.tools,
        )
        for _, binding in rows
        if binding is not None
    ]

    # Compute current user permission
    current_user_permission = None
    if user_id and agent.owner_id == user_id:
        current_user_permission = "owner"
    elif user_role == WorkspaceRole.admin:
        current_user_permission = "admin"
    elif user_id:
        perm_result = await db.execute(
            select(AgentUserPermissionDB.permission).where(
                AgentUserPermissionDB.agent_id == agent_id,
                AgentUserPermissionDB.user_id == user_id,
            )
        )
        perm = perm_result.scalar_one_or_none()
        if perm:
            current_user_permission = perm.value

    return AgentRead(
        **agent.model_dump(),
        mcp_servers=mcp_servers,
        current_user_permission=current_user_permission,
    )
