import logging
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
from app.auth.dependencies import get_current_user
from app.database import get_db
from app.mcp.client.auth import ServerlessOAuthProvider, build_oauth_client_metadata
from app.mcp.client.storage import TokenStorageFactory
from app.mcp.servers.models import MCPAuthType, MCPServerDB
from app.mcp.servers.router import connect_to_server
from app.users.models import UserDB

logger = logging.getLogger(__name__)

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


async def check_oauth_connected(
    mcp_server: MCPServerDB, user_id: str
) -> bool:
    """Check if user has OAuth credentials for the MCP server."""
    storage = TokenStorageFactory().get_storage(user_id, str(mcp_server.id))
    client_metadata = build_oauth_client_metadata(mcp_server)

    provider = ServerlessOAuthProvider(
        server_url=mcp_server.url,
        client_metadata=client_metadata,
        storage=storage
    )

    await provider._initialize()
    tokens = await provider.context.storage.get_tokens()
    return tokens is not None


async def fetch_and_save_tools(
    db_binding: AgentMCPServerBindingDB,
    mcp_server: MCPServerDB,
    user_id: str,
    db: AsyncSession,
) -> None:
    """Fetch tools from MCP server and save them to the binding."""
    try:
        async with connect_to_server(mcp_server, user_id, db) as (_, tools):
            # Build tools dict with all tools set to "always_allow"
            tools_dict = {tool.name: "always_allow" for tool in tools}
            db_binding.tools = tools_dict
            db.add(db_binding)
            await db.commit()
            await db.refresh(db_binding)
    except Exception as e:
        # Log the error but don't fail the binding creation
        logger.warning(f"Failed to fetch tools for MCP server {mcp_server.id}: {e}")


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
    current_user: UserDB = Depends(get_current_user),
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
        # Update existing binding
        if binding.tools is not None:
            existing_binding.tools = binding.tools
        db.add(existing_binding)
        await db.commit()
        await db.refresh(existing_binding)
        return existing_binding

    # Create new binding with tools = null initially
    db_binding = AgentMCPServerBindingDB(
        agent_id=agent_id,
        mcp_server_id=server_id,
        tools=None,  # Start with null, will populate after
    )
    db.add(db_binding)
    await db.commit()
    await db.refresh(db_binding)

    # Try to fetch and save tools based on auth type
    user_id = str(current_user.id)

    if mcp_server.auth_type in [MCPAuthType.none, MCPAuthType.api_key]:
        # For no-auth or API key, directly fetch tools
        await fetch_and_save_tools(db_binding, mcp_server, user_id, db)
    elif mcp_server.auth_type == MCPAuthType.oauth2:
        # For OAuth, check if user has credentials first
        is_connected = await check_oauth_connected(mcp_server, user_id)
        if is_connected:
            await fetch_and_save_tools(db_binding, mcp_server, user_id, db)
        # If not connected, just return the binding without tools
        # OAuth connection will be handled later

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

    # Handle tools update: merge with existing tools if present
    if "tools" in update_data and update_data["tools"] is not None:
        existing_tools = db_binding.tools or {}
        # Merge: update existing tools with new values
        merged_tools = {**existing_tools, **update_data["tools"]}
        update_data["tools"] = merged_tools

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


@router.post(
    "/{agent_id}/mcp-servers/{server_id}/sync-tools",
    response_model=AgentMCPServerBindingRead,
)
async def sync_tools(
    agent_id: UUID,
    server_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
) -> AgentMCPServerBindingRead:
    """Sync tools from MCP server to the binding.

    This endpoint fetches tools from the MCP server and saves them to the binding
    with 'always_allow' status. Useful after OAuth connection is established.
    """
    # Get the MCP server
    result = await db.execute(select(MCPServerDB).where(MCPServerDB.id == server_id))
    mcp_server = result.scalar_one_or_none()
    if not mcp_server:
        raise HTTPException(status_code=404, detail="MCP server not found")

    # Get the binding
    result = await db.execute(
        select(AgentMCPServerBindingDB).where(
            AgentMCPServerBindingDB.agent_id == agent_id,
            AgentMCPServerBindingDB.mcp_server_id == server_id,
        )
    )
    db_binding = result.scalar_one_or_none()
    if not db_binding:
        raise HTTPException(status_code=404, detail="Binding not found")

    # Fetch and save tools
    await fetch_and_save_tools(db_binding, mcp_server, str(current_user.id), db)

    return db_binding
