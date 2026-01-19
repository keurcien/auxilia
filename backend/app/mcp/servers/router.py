import httpx

from contextlib import asynccontextmanager
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.database import get_db
from app.mcp.client.auth import ServerlessOAuthProvider, build_oauth_client_metadata
from app.mcp.client.storage import (
    RedisTokenStorage,
    TokenStorageFactory,
)
from app.mcp.servers.encryption import encrypt_api_key, decrypt_api_key
from app.mcp.servers.models import (
    MCPAuthType,
    MCPServerAPIKeyDB,
    MCPServerCreate,
    MCPServerDB,
    MCPServerRead,
    MCPServerUpdate,
    OfficialMCPServerDB,
    OfficialMCPServerRead
)

router = APIRouter(prefix="/mcp-servers", tags=["mcp-servers"])


async def get_mcp_server_dependency(
    mcp_server_id: str, db: AsyncSession = Depends(get_db)
) -> MCPServerDB:
    result = await db.execute(
        select(MCPServerDB).where(MCPServerDB.id == mcp_server_id)
    )
    return result.scalar_one_or_none()


async def get_mcp_server_api_key(
    mcp_server_id: UUID, db: AsyncSession
) -> str | None:
    """Get the decrypted API key for an MCP server.

    Args:
        mcp_server_id: The MCP server ID
        db: Database session

    Returns:
        The decrypted API key or None if not found
    """
    result = await db.execute(
        select(MCPServerAPIKeyDB).where(
            MCPServerAPIKeyDB.mcp_server_id == mcp_server_id
        )
    )
    api_key_record = result.scalar_one_or_none()
    if api_key_record:
        return decrypt_api_key(api_key_record.key_encrypted)
    return None


@router.post("/", response_model=MCPServerRead, status_code=201)
async def create_mcp_server(
    server: MCPServerCreate, db: AsyncSession = Depends(get_db)
) -> MCPServerRead:
    db_server = MCPServerDB.model_validate(server)
    db.add(db_server)
    await db.flush()

    if server.auth_type == MCPAuthType.api_key and server.api_key:
        encrypted_key = encrypt_api_key(server.api_key)
        api_key_record = MCPServerAPIKeyDB(
            mcp_server_id=db_server.id,
            key_encrypted=encrypted_key,
            created_by=None,  # TODO: Add user context when authentication is implemented
        )
        db.add(api_key_record)
    elif server.auth_type == MCPAuthType.api_key and not server.api_key:
        raise HTTPException(
            status_code=400,
            detail="API key is required when auth_type is 'api_key'"
        )

    await db.commit()
    await db.refresh(db_server)
    return db_server


@router.get("/", response_model=list[MCPServerRead])
async def get_mcp_servers(db: AsyncSession = Depends(get_db)) -> list[MCPServerRead]:
    result = await db.execute(select(MCPServerDB).order_by(MCPServerDB.created_at.asc()))
    servers = result.scalars().all()
    return list(servers)

@router.get("/official", response_model=list[OfficialMCPServerRead])
async def get_official_mcp_servers(db: AsyncSession = Depends(get_db)) -> list[OfficialMCPServerRead]:
    stmt = (
        select(
            OfficialMCPServerDB,
            MCPServerDB.id.isnot(None).label("is_configured")
        )
        .outerjoin(
            MCPServerDB,
            OfficialMCPServerDB.url == MCPServerDB.url
        )
        .order_by(OfficialMCPServerDB.created_at.asc())
    )
    result = await db.execute(stmt)
    rows = result.all()
    return [OfficialMCPServerRead(
        **row[0].model_dump(),
        is_installed=row[1]
    ) for row in rows]


@router.get("/{server_id}", response_model=MCPServerRead)
async def get_mcp_server(
    server_id: UUID, db: AsyncSession = Depends(get_db)
) -> MCPServerRead:
    result = await db.execute(select(MCPServerDB).where(MCPServerDB.id == server_id))
    server = result.scalar_one_or_none()
    if not server:
        raise HTTPException(status_code=404, detail="MCP server not found")
    return server


@router.patch("/{server_id}", response_model=MCPServerRead)
async def update_mcp_server(
    server_id: UUID, server_update: MCPServerUpdate, db: AsyncSession = Depends(get_db)
) -> MCPServerRead:
    result = await db.execute(select(MCPServerDB).where(MCPServerDB.id == server_id))
    db_server = result.scalar_one_or_none()
    if not db_server:
        raise HTTPException(status_code=404, detail="MCP server not found")

    update_data = server_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_server, key, value)

    db.add(db_server)
    await db.commit()
    await db.refresh(db_server)
    return db_server


@router.delete("/{server_id}", status_code=204)
async def delete_mcp_server(
    server_id: UUID, db: AsyncSession = Depends(get_db)
) -> None:
    result = await db.execute(select(MCPServerDB).where(MCPServerDB.id == server_id))
    db_server = result.scalar_one_or_none()
    if not db_server:
        raise HTTPException(status_code=404, detail="MCP server not found")

    await db.delete(db_server)
    await db.commit()


@router.get("/{mcp_server_id}/oauth/callback")
async def oauth_callback(
    code: str = Query(..., description="Authorization code from OAuth provider"),
    state: str | None = Query(None, description="State parameter from OAuth provider"),
    mcp_server: MCPServerDB = Depends(get_mcp_server_dependency),
):
    client_metadata = build_oauth_client_metadata(mcp_server)
    storage = TokenStorageFactory().get_storage(mcp_server.id)
    provider = ServerlessOAuthProvider(
        server_url=mcp_server.url,
        client_metadata=client_metadata,
        storage=storage
    )

    await provider.manual_exchange(code, state)

    return JSONResponse(
        status_code=200,
        content={
            "status": "success",
            "message": "Authorization code received and published",
        },
    )


@asynccontextmanager
async def connect_to_server(mcp_server: MCPServerDB, storage: RedisTokenStorage, db: AsyncSession):
    """Connect to an MCP server and initialize session.

    Similar to the pattern from https://modelcontextprotocol.info/docs/tutorials/building-a-client/
    but adapted for web API context with proper resource management.

    Args:
        mcp_server: MCP server configuration
        storage: Storage instance for OAuth tokens

    Yields:
        tuple: (session, tools) - Initialized session and available tools

    Raises:
        OAuthAuthorizationRequired: If OAuth authorization is needed
    """
    if mcp_server.auth_type == MCPAuthType.oauth2:
        client_metadata = build_oauth_client_metadata(mcp_server)
        provider = ServerlessOAuthProvider(
            server_url=mcp_server.url,
            client_metadata=client_metadata,
            storage=storage,
        )
        client_args={"url": mcp_server.url, "auth": provider}
    elif mcp_server.auth_type == MCPAuthType.api_key:
        api_key = await get_mcp_server_api_key(mcp_server.id, db)
        client_args={"url": mcp_server.url, "headers": {"Authorization": f"Bearer {api_key}"}}
    else:
        client_args={"url": mcp_server.url}

    async with streamablehttp_client(**client_args) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            response = await session.list_tools()
            tools = response.tools

            yield session, tools


@router.get("/{mcp_server_id}/list-tools")
async def list_tools(mcp_server: MCPServerDB = Depends(get_mcp_server_dependency), db: AsyncSession = Depends(get_db)):
    """List available tools from an MCP server.

    Connects to the server, retrieves available tools, and returns them.
    OAuth errors are handled by the global exception handler.
    """
    storage = TokenStorageFactory().get_storage(mcp_server.id)
    async with connect_to_server(mcp_server, storage, db) as (_, tools):
        return [{"name": tool.name, "description": tool.description} for tool in tools]


@router.get("/{mcp_server_id}/is-connected")
async def is_connected(mcp_server: MCPServerDB = Depends(get_mcp_server_dependency)):
    """Check if an MCP server is connected.

    Returns True if:
    - The MCP server does not require OAuth, OR
    - The MCP server requires OAuth and a valid token is available in storage

    Returns False if:
    - The MCP server requires OAuth but no token is available
    """
    if mcp_server.auth_type in [MCPAuthType.none, MCPAuthType.api_key]:
        return {"connected": True}

    storage = TokenStorageFactory().get_storage(mcp_server.id)
    client_metadata = build_oauth_client_metadata(mcp_server)
    provider = ServerlessOAuthProvider(
        server_url=mcp_server.url,
        client_metadata=client_metadata,
        storage=storage,
    )

    
    await provider._initialize()
    tokens = await provider.context.storage.get_tokens()
    
    if not tokens:
        return {"connected": False}
    return {"connected": True}
