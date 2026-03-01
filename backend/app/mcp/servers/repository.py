from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.mcp.servers.encryption import decrypt_api_key, encrypt_api_key
from app.mcp.servers.models import (
    MCPServerAPIKeyDB,
    MCPServerCreate,
    MCPServerDB,
    MCPServerOAuthCredentialsDB,
    OfficialMCPServerDB,
)


class MCPServerRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get(self, server_id: UUID) -> MCPServerDB | None:
        result = await self.db.execute(
            select(MCPServerDB).where(MCPServerDB.id == server_id)
        )
        return result.scalar_one_or_none()

    async def list(self) -> list[MCPServerDB]:
        result = await self.db.execute(
            select(MCPServerDB).order_by(MCPServerDB.created_at.asc())
        )
        return list(result.scalars().all())

    async def create(self, data: MCPServerCreate) -> MCPServerDB:
        db_server = MCPServerDB.model_validate(data)
        self.db.add(db_server)
        await self.db.flush()
        return db_server

    async def update(self, server: MCPServerDB, data: dict) -> MCPServerDB:
        for key, value in data.items():
            setattr(server, key, value)
        self.db.add(server)
        await self.db.commit()
        await self.db.refresh(server)
        return server

    async def delete(self, server: MCPServerDB) -> None:
        await self.db.delete(server)
        await self.db.commit()

    async def get_api_key(self, server_id: UUID) -> str | None:
        result = await self.db.execute(
            select(MCPServerAPIKeyDB).where(
                MCPServerAPIKeyDB.mcp_server_id == server_id
            )
        )
        api_key_record = result.scalar_one_or_none()
        if api_key_record:
            return decrypt_api_key(api_key_record.key_encrypted)
        return None

    async def save_api_key(self, server_id: UUID, api_key: str) -> None:
        encrypted_key = encrypt_api_key(api_key)
        api_key_record = MCPServerAPIKeyDB(
            mcp_server_id=server_id,
            key_encrypted=encrypted_key,
            created_by=None,
        )
        self.db.add(api_key_record)

    async def get_oauth_credentials(self, server_id: UUID) -> MCPServerOAuthCredentialsDB | None:
        result = await self.db.execute(
            select(MCPServerOAuthCredentialsDB).where(
                MCPServerOAuthCredentialsDB.mcp_server_id == server_id
            )
        )
        return result.scalar_one_or_none()

    async def save_oauth_credentials(
        self,
        server_id: UUID,
        client_id: str,
        client_secret: str,
        auth_method: str | None,
    ) -> None:
        encrypted_secret = encrypt_api_key(client_secret)
        oauth_credentials = MCPServerOAuthCredentialsDB(
            mcp_server_id=server_id,
            client_id=client_id,
            client_secret_encrypted=encrypted_secret,
            token_endpoint_auth_method=auth_method,
            created_by=None,
        )
        self.db.add(oauth_credentials)

    async def list_official(self) -> list[tuple[OfficialMCPServerDB, bool]]:
        stmt = (
            select(
                OfficialMCPServerDB,
                MCPServerDB.id.isnot(None).label("is_configured"),
            )
            .outerjoin(MCPServerDB, OfficialMCPServerDB.url == MCPServerDB.url)
            .order_by(OfficialMCPServerDB.created_at.asc())
        )
        result = await self.db.execute(stmt)
        return result.all()


# Standalone wrappers — importable without circular deps
async def get_mcp_server_api_key(server_id: UUID, db: AsyncSession) -> str | None:
    """Get the decrypted API key for an MCP server."""
    return await MCPServerRepository(db).get_api_key(server_id)


async def get_mcp_server_oauth_credentials(
    server_id: UUID, db: AsyncSession
) -> MCPServerOAuthCredentialsDB | None:
    """Get OAuth credentials for an MCP server."""
    return await MCPServerRepository(db).get_oauth_credentials(server_id)
