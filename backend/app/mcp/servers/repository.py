from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.mcp.servers.encryption import (
    decrypt_value as decrypt_api_key,
    encrypt_value as encrypt_api_key,
)
from app.mcp.servers.models import (
    MCPServerAPIKeyDB,
    MCPServerDB,
    MCPServerOAuthCredentialsDB,
    OfficialMCPServerDB,
)
from app.mcp.servers.schemas import MCPServerCreate
from app.repository import BaseRepository


class MCPServerRepository(BaseRepository[MCPServerDB]):
    def __init__(self, db: AsyncSession):
        super().__init__(MCPServerDB, db)

    async def list(self) -> list[MCPServerDB]:
        stmt = select(MCPServerDB).order_by(MCPServerDB.created_at.asc())
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def create(self, data: MCPServerCreate) -> MCPServerDB:
        db_server = MCPServerDB.model_validate(data)
        self.db.add(db_server)
        await self.db.flush()
        return db_server

    async def get_api_key(self, server_id: UUID) -> str | None:
        stmt = select(MCPServerAPIKeyDB).where(
            MCPServerAPIKeyDB.mcp_server_id == server_id
        )
        result = await self.db.execute(stmt)
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
        stmt = select(MCPServerOAuthCredentialsDB).where(
            MCPServerOAuthCredentialsDB.mcp_server_id == server_id
        )
        result = await self.db.execute(stmt)
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
