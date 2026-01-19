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
        AgentMCPServer(id=binding.mcp_server_id, enabled_tools=binding.enabled_tools)
        for _, binding in rows
        if binding is not None
    ]

    return AgentRead(**agent.model_dump(), mcp_servers=mcp_servers)
