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
)


async def read_agents(
    db: AsyncSession, owner_id: UUID | None = None
) -> list[AgentRead]:
    query = (
        select(AgentDB, AgentMCPServerBindingDB)
        .outerjoin(
            AgentMCPServerBindingDB, AgentDB.id == AgentMCPServerBindingDB.agent_id
        )
        .order_by(AgentDB.created_at.asc())
    )
    if owner_id:
        query = query.where(AgentDB.owner_id == owner_id)

    result = await db.execute(query)
    rows = result.all()

    agents_map: dict[UUID, AgentDB] = {}
    bindings_map: dict[UUID, list[AgentMCPServer]] = defaultdict(list)

    for agent, binding in rows:
        agents_map[agent.id] = agent
        if binding is not None:
            bindings_map[agent.id].append(
                AgentMCPServer(id=binding.mcp_server_id, tools=binding.tools)
            )

    return [
        AgentRead(**agent.model_dump(), mcp_servers=bindings_map.get(agent.id, []))
        for agent in agents_map.values()
    ]


async def read_agent(agent_id: UUID, db: AsyncSession) -> AgentRead:
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

    return AgentRead(**agent.model_dump(), mcp_servers=mcp_servers)
