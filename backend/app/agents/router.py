from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.agents.models import (
    AgentCreate,
    AgentDB,
    AgentMCPServerBindingCreate,
    AgentMCPServerBindingDB,
    AgentMCPServerBindingRead,
    AgentMCPServerBindingUpdate,
    AgentRead,
    AgentUpdate,
)
from app.agents.utils import read_agent
from app.database import get_db
from app.mcp.servers.models import MCPServerDB

router = APIRouter(prefix="/agents", tags=["agents"])


@router.post("/", response_model=AgentRead, status_code=201)
async def create_agent(
    agent: AgentCreate, db: AsyncSession = Depends(get_db)
) -> AgentRead:
    db_agent = AgentDB.model_validate(agent)
    db.add(db_agent)
    await db.commit()
    await db.refresh(db_agent)
    return db_agent


@router.get("/", response_model=list[AgentRead])
async def get_agents(
    owner_id: UUID | None = None, db: AsyncSession = Depends(get_db)
) -> list[AgentRead]:
    query = select(AgentDB).order_by(AgentDB.created_at.asc())
    if owner_id:
        query = query.where(AgentDB.owner_id == owner_id)
    result = await db.execute(query)
    agents = result.scalars().all()
    return list(agents)


@router.get("/{agent_id}", response_model=AgentRead, response_model_by_alias=True)
async def get_agent(agent_id: UUID, db: AsyncSession = Depends(get_db)) -> AgentRead:
    return await read_agent(agent_id, db)


@router.patch("/{agent_id}", response_model=AgentRead)
async def update_agent(
    agent_id: UUID, agent_update: AgentUpdate, db: AsyncSession = Depends(get_db)
) -> AgentRead:
    result = await db.execute(select(AgentDB).where(AgentDB.id == agent_id))
    db_agent = result.scalar_one_or_none()
    if not db_agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    update_data = agent_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_agent, key, value)

    db.add(db_agent)
    await db.commit()
    await db.refresh(db_agent)
    return db_agent


@router.delete("/{agent_id}", status_code=204)
async def delete_agent(agent_id: UUID, db: AsyncSession = Depends(get_db)) -> None:
    result = await db.execute(select(AgentDB).where(AgentDB.id == agent_id))
    db_agent = result.scalar_one_or_none()
    if not db_agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    await db.delete(db_agent)
    await db.commit()


@router.post(
    "/{agent_id}/mcp-servers/{server_id}",
    response_model=AgentMCPServerBindingRead,
    status_code=201,
)
async def create_or_update_binding(
    agent_id: UUID,
    server_id: UUID,
    binding: AgentMCPServerBindingCreate,
    db: AsyncSession = Depends(get_db),
) -> AgentMCPServerBindingRead:
    result = await db.execute(select(MCPServerDB).where(MCPServerDB.id == server_id))
    mcp_server = result.scalar_one_or_none()
    if not mcp_server:
        raise HTTPException(status_code=404, detail="MCP server not found")

    result = await db.execute(
        select(AgentMCPServerBindingDB).where(
            AgentMCPServerBindingDB.agent_id == agent_id,
            AgentMCPServerBindingDB.mcp_server_id == server_id,
        )
    )
    existing_binding = result.scalar_one_or_none()

    if existing_binding:
        existing_binding.enabled_tools = binding.enabled_tools
        db.add(existing_binding)
        await db.commit()
        await db.refresh(existing_binding)
        return existing_binding
    else:
        db_binding = AgentMCPServerBindingDB(
            agent_id=agent_id,
            mcp_server_id=server_id,
            enabled_tools=binding.enabled_tools,
        )
        db.add(db_binding)
        await db.commit()
        await db.refresh(db_binding)
        return db_binding


@router.patch(
    "/{agent_id}/mcp-servers/{server_id}", response_model=AgentMCPServerBindingRead
)
async def update_binding(
    agent_id: UUID,
    server_id: UUID,
    binding_update: AgentMCPServerBindingUpdate,
    db: AsyncSession = Depends(get_db),
) -> AgentMCPServerBindingRead:
    result = await db.execute(
        select(AgentMCPServerBindingDB).where(
            AgentMCPServerBindingDB.agent_id == agent_id,
            AgentMCPServerBindingDB.mcp_server_id == server_id,
        )
    )
    db_binding = result.scalar_one_or_none()
    if not db_binding:
        raise HTTPException(status_code=404, detail="Binding not found")

    update_data = binding_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_binding, key, value)

    db.add(db_binding)
    await db.commit()
    await db.refresh(db_binding)
    return db_binding


@router.delete("/{agent_id}/mcp-servers/{server_id}", status_code=204)
async def delete_binding(
    agent_id: UUID, server_id: UUID, db: AsyncSession = Depends(get_db)
) -> None:
    result = await db.execute(
        select(AgentMCPServerBindingDB).where(
            AgentMCPServerBindingDB.agent_id == agent_id,
            AgentMCPServerBindingDB.mcp_server_id == server_id,
        )
    )
    db_binding = result.scalar_one_or_none()
    if not db_binding:
        raise HTTPException(status_code=404, detail="Binding not found")

    await db.delete(db_binding)
    await db.commit()
