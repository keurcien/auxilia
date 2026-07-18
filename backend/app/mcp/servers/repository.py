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

    async def list_with_oauth_client_id(
        self,
    ) -> list[tuple[MCPServerDB, str | None]]:
        """List servers alongside their static OAuth client_id (None for DCR /
        non-OAuth servers), via a single LEFT JOIN to avoid an N+1."""
        stmt = (
            select(MCPServerDB, MCPServerOAuthCredentialsDB.client_id)
            .outerjoin(
                MCPServerOAuthCredentialsDB,
                MCPServerOAuthCredentialsDB.mcp_server_id == MCPServerDB.id,
            )
            .order_by(MCPServerDB.created_at.asc())
        )
        result = await self.db.execute(stmt)
        return result.all()

    async def get_by_url(self, url: str) -> MCPServerDB | None:
        stmt = select(MCPServerDB).where(MCPServerDB.url == url)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

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

    async def create_or_update_api_key(self, server_id: UUID, api_key: str) -> None:
        encrypted_key = encrypt_api_key(api_key)
        stmt = select(MCPServerAPIKeyDB).where(
            MCPServerAPIKeyDB.mcp_server_id == server_id
        )
        result = await self.db.execute(stmt)
        api_key_record = result.scalar_one_or_none()
        if api_key_record:
            api_key_record.key_encrypted = encrypted_key
        else:
            self.db.add(
                MCPServerAPIKeyDB(
                    mcp_server_id=server_id,
                    key_encrypted=encrypted_key,
                    created_by=None,
                )
            )
        await self.db.flush()

    async def get_oauth_credentials(
        self, server_id: UUID
    ) -> MCPServerOAuthCredentialsDB | None:
        stmt = select(MCPServerOAuthCredentialsDB).where(
            MCPServerOAuthCredentialsDB.mcp_server_id == server_id
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def create_or_update_oauth_credentials(
        self,
        server_id: UUID,
        client_id: str,
        client_secret: str,
        auth_method: str | None,
    ) -> None:
        encrypted_secret = encrypt_api_key(client_secret)
        oauth_credentials = await self.get_oauth_credentials(server_id)
        if oauth_credentials:
            oauth_credentials.client_id = client_id
            oauth_credentials.client_secret_encrypted = encrypted_secret
            oauth_credentials.token_endpoint_auth_method = auth_method
        else:
            self.db.add(
                MCPServerOAuthCredentialsDB(
                    mcp_server_id=server_id,
                    client_id=client_id,
                    client_secret_encrypted=encrypted_secret,
                    token_endpoint_auth_method=auth_method,
                    created_by=None,
                )
            )
        await self.db.flush()

    async def update_oauth_credentials(
        self,
        server_id: UUID,
        *,
        client_id: str | None = None,
        client_secret: str | None = None,
        auth_method: str | None = None,
    ) -> None:
        """Patch stored OAuth credentials: only provided fields change, so a
        blank client_secret keeps the existing one while client_id is edited.

        When no credentials exist yet, fresh ones are created only if BOTH
        client_id and client_secret are supplied (a secret can't be omitted at
        creation time); otherwise this is a no-op.
        """
        creds = await self.get_oauth_credentials(server_id)
        if not creds:
            if client_id and client_secret:
                await self.create_or_update_oauth_credentials(
                    server_id, client_id, client_secret, auth_method
                )
            return
        if client_id is not None:
            creds.client_id = client_id
        if client_secret is not None:
            creds.client_secret_encrypted = encrypt_api_key(client_secret)
        if auth_method is not None:
            creds.token_endpoint_auth_method = auth_method
        await self.db.flush()

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
