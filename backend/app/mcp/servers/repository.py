from __future__ import annotations

from collections.abc import Collection, Sequence
from uuid import UUID, uuid4

from sqlalchemy import delete, func, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.agents.models import AgentDB, AgentMCPServerDB
from app.mcp.servers.models import (
    MCPCredentialScope,
    MCPServerAPIKeyDB,
    MCPServerDB,
    MCPServerImageDB,
    MCPServerOAuthCredentialsDB,
    MCPServerServiceCredentialDB,
    MCPServerTeamDB,
    MCPServerUserCredentialDB,
    ServiceCredentialProvider,
)
from app.mcp.servers.schemas import MCPServerCreate
from app.repository import BaseRepository
from app.utils.encryption import decrypt_value, encrypt_value


class MCPServerRepository(BaseRepository[MCPServerDB]):
    def __init__(self, db: AsyncSession, workspace_id: UUID | None = None):
        super().__init__(MCPServerDB, db)
        self.workspace_id = workspace_id

    def _scope(self, stmt):
        if self.workspace_id is not None:
            return stmt.where(MCPServerDB.workspace_id == self.workspace_id)
        return stmt

    async def get_scoped(self, server_id: UUID) -> MCPServerDB | None:
        stmt = self._scope(select(MCPServerDB).where(MCPServerDB.id == server_id))
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_scoped_for_update(self, server_id: UUID) -> MCPServerDB | None:
        stmt = self._scope(
            select(MCPServerDB).where(MCPServerDB.id == server_id).with_for_update()
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def list(self) -> list[MCPServerDB]:
        stmt = self._scope(select(MCPServerDB)).order_by(MCPServerDB.created_at.asc())
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def mark_managed(
        self,
        server: MCPServerDB,
        *,
        managed_by: str,
        resource_id: UUID,
    ) -> MCPServerDB:
        server.managed_by = managed_by
        server.managed_resource_id = resource_id
        self.db.add(server)
        await self.db.flush()
        await self.db.refresh(server)
        return server

    async def list_by_ids(self, server_ids: Collection[UUID]) -> Sequence[MCPServerDB]:
        """The servers behind a set of agent bindings, in one `IN` query.

        Order is unspecified — every caller looks rows up by id. An empty
        `server_ids` short-circuits: `IN ()` is a round-trip for a known-empty
        answer.
        """
        if not server_ids:
            return []
        stmt = self._scope(select(MCPServerDB).where(MCPServerDB.id.in_(server_ids)))
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def list_with_credential_metadata(
        self,
    ) -> list[
        tuple[
            MCPServerDB,
            str | None,
            ServiceCredentialProvider | None,
            str | None,
            list[str] | None,
        ]
    ]:
        """List servers with safe credential metadata via two LEFT JOINs."""
        stmt = (
            select(
                MCPServerDB,
                MCPServerOAuthCredentialsDB.client_id,
                MCPServerServiceCredentialDB.provider,
                MCPServerServiceCredentialDB.principal,
                MCPServerServiceCredentialDB.scopes,
            )
            .outerjoin(
                MCPServerOAuthCredentialsDB,
                MCPServerOAuthCredentialsDB.mcp_server_id == MCPServerDB.id,
            )
            .outerjoin(
                MCPServerServiceCredentialDB,
                MCPServerServiceCredentialDB.mcp_server_id == MCPServerDB.id,
            )
            .order_by(MCPServerDB.created_at.asc())
        )
        stmt = self._scope(stmt)
        result = await self.db.execute(stmt)
        return result.all()

    async def get_image(self, server_id: UUID) -> MCPServerImageDB | None:
        stmt = select(MCPServerImageDB).where(
            MCPServerImageDB.mcp_server_id == server_id
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def images_by_server_ids(
        self, server_ids: Collection[UUID]
    ) -> dict[UUID, MCPServerImageDB]:
        if not server_ids:
            return {}
        stmt = select(MCPServerImageDB).where(
            MCPServerImageDB.mcp_server_id.in_(server_ids)
        )
        result = await self.db.execute(stmt)
        return {image.mcp_server_id: image for image in result.scalars().all()}

    async def _lock_image_parent(self, server_id: UUID) -> None:
        stmt = (
            select(MCPServerDB.id).where(MCPServerDB.id == server_id).with_for_update()
        )
        await self.db.execute(stmt)

    async def set_image(
        self,
        server_id: UUID,
        *,
        data: bytes,
        media_type: str,
        sha256: str,
        revision: UUID,
    ) -> None:
        await self._lock_image_parent(server_id)
        image = await self.get_image(server_id)
        if image is None:
            image = MCPServerImageDB(
                mcp_server_id=server_id,
                data=data,
                media_type=media_type,
                sha256=sha256,
            )
        else:
            image.data = data
            image.media_type = media_type
            image.sha256 = sha256
        self.db.add(image)
        stmt = (
            update(MCPServerDB)
            .where(MCPServerDB.id == server_id)
            .values(image_revision=revision)
        )
        await self.db.execute(stmt)
        await self.db.flush()

    async def delete_image(self, server_id: UUID) -> None:
        await self._lock_image_parent(server_id)
        stmt = delete(MCPServerImageDB).where(
            MCPServerImageDB.mcp_server_id == server_id
        )
        await self.db.execute(stmt)
        stmt = (
            update(MCPServerDB)
            .where(MCPServerDB.id == server_id)
            .values(image_revision=None)
        )
        await self.db.execute(stmt)
        await self.db.flush()

    async def create(self, data: MCPServerCreate, owner_id: UUID) -> MCPServerDB:
        if self.workspace_id is None:
            raise RuntimeError("workspace_id is required to create an MCP server")
        db_server = MCPServerDB.model_validate(
            data, update={"workspace_id": self.workspace_id, "owner_id": owner_id}
        )
        self.db.add(db_server)
        await self.db.flush()
        return db_server

    async def create_copy(
        self, source: MCPServerDB, *, name: str, owner_id: UUID
    ) -> MCPServerDB:
        """Copy a server with its audience, image and shared credentials.

        Encrypted values are copied verbatim. Per-user state (personal
        credentials, OAuth tokens in Redis) stays with the source.
        """
        image = await self.get_image(source.id)
        copy = MCPServerDB(
            workspace_id=source.workspace_id,
            name=name,
            url=source.url,
            auth_type=source.auth_type,
            credential_scope=source.credential_scope,
            personal_header_names=list(source.personal_header_names),
            icon_url=source.icon_url,
            description=source.description,
            group=source.group,
            owner_id=owner_id,
            visibility=source.visibility,
            disabled_tools=list(source.disabled_tools),
            image_revision=uuid4() if image is not None else None,
        )
        self.db.add(copy)
        await self.db.flush()

        team_ids = await self.list_team_ids(source.id)
        if team_ids:
            await self.set_team_ids(copy.id, team_ids)

        if image is not None:
            self.db.add(
                MCPServerImageDB(
                    mcp_server_id=copy.id,
                    data=image.data,
                    media_type=image.media_type,
                    sha256=image.sha256,
                )
            )

        stmt = select(MCPServerAPIKeyDB).where(
            MCPServerAPIKeyDB.mcp_server_id == source.id
        )
        api_key = (await self.db.execute(stmt)).scalar_one_or_none()
        if api_key is not None:
            self.db.add(
                MCPServerAPIKeyDB(
                    mcp_server_id=copy.id,
                    key_encrypted=api_key.key_encrypted,
                    created_by=None,
                )
            )

        oauth = await self.get_oauth_credentials(source.id)
        if oauth is not None:
            self.db.add(
                MCPServerOAuthCredentialsDB(
                    mcp_server_id=copy.id,
                    client_id=oauth.client_id,
                    client_secret_encrypted=oauth.client_secret_encrypted,
                    token_endpoint_auth_method=oauth.token_endpoint_auth_method,
                    created_by=None,
                )
            )

        service_credential = await self.get_service_credential(source.id)
        if service_credential is not None:
            self.db.add(
                MCPServerServiceCredentialDB(
                    mcp_server_id=copy.id,
                    provider=service_credential.provider,
                    credentials_encrypted=service_credential.credentials_encrypted,
                    scopes=list(service_credential.scopes),
                    principal=service_credential.principal,
                    created_by=None,
                )
            )

        await self.db.flush()
        return copy

    async def list_team_ids(self, server_id: UUID) -> list[UUID]:
        stmt = select(MCPServerTeamDB.team_id).where(
            MCPServerTeamDB.mcp_server_id == server_id
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def list_team_ids_for_servers(
        self, server_ids: Collection[UUID]
    ) -> dict[UUID, list[UUID]]:
        if not server_ids:
            return {}
        stmt = select(MCPServerTeamDB.mcp_server_id, MCPServerTeamDB.team_id).where(
            MCPServerTeamDB.mcp_server_id.in_(server_ids)
        )
        result = await self.db.execute(stmt)
        grouped: dict[UUID, list[UUID]] = {}
        for server_id, team_id in result.all():
            grouped.setdefault(server_id, []).append(team_id)
        return grouped

    async def set_team_ids(self, server_id: UUID, team_ids: Collection[UUID]) -> None:
        stmt = delete(MCPServerTeamDB).where(MCPServerTeamDB.mcp_server_id == server_id)
        await self.db.execute(stmt)
        self.db.add_all(
            [
                MCPServerTeamDB(mcp_server_id=server_id, team_id=team_id)
                for team_id in dict.fromkeys(team_ids)
            ]
        )
        await self.db.flush()

    async def get_api_key(self, server_id: UUID) -> str | None:
        stmt = select(MCPServerAPIKeyDB).where(
            MCPServerAPIKeyDB.mcp_server_id == server_id
        )
        result = await self.db.execute(stmt)
        api_key_record = result.scalar_one_or_none()
        if api_key_record:
            return decrypt_value(api_key_record.key_encrypted)
        return None

    async def create_or_update_api_key(self, server_id: UUID, api_key: str) -> None:
        encrypted_key = encrypt_value(api_key)
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

    async def delete_credentials(self, server_id: UUID, *, api_key: bool) -> None:
        """Drop the stored credentials a server no longer has any use for.

        `api_key=True` removes the API-key row, otherwise the OAuth-credentials
        row. Called when a server's `auth_type` changes: the leftover row is
        dead config that `list_responses` already has to gate on the current
        auth type to avoid showing.
        """
        model = MCPServerAPIKeyDB if api_key else MCPServerOAuthCredentialsDB
        stmt = delete(model).where(model.mcp_server_id == server_id)
        await self.db.execute(stmt)
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
        encrypted_secret = encrypt_value(client_secret)
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
            creds.client_secret_encrypted = encrypt_value(client_secret)
        if auth_method is not None:
            creds.token_endpoint_auth_method = auth_method
        await self.db.flush()

    async def get_service_credential(
        self, server_id: UUID
    ) -> MCPServerServiceCredentialDB | None:
        stmt = select(MCPServerServiceCredentialDB).where(
            MCPServerServiceCredentialDB.mcp_server_id == server_id
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def create_or_update_service_credential(
        self,
        server_id: UUID,
        *,
        provider: ServiceCredentialProvider,
        credentials_json: str,
        scopes: Collection[str],
        principal: str | None,
    ) -> None:
        row = await self.get_service_credential(server_id)
        if row is None:
            row = MCPServerServiceCredentialDB(
                mcp_server_id=server_id,
                provider=provider,
                credentials_encrypted=encrypt_value(credentials_json),
                scopes=list(scopes),
                principal=principal,
                created_by=None,
            )
            self.db.add(row)
        else:
            row.provider = provider
            row.credentials_encrypted = encrypt_value(credentials_json)
            row.scopes = list(scopes)
            row.principal = principal
        await self.db.flush()

    async def delete_service_credential(self, server_id: UUID) -> None:
        stmt = delete(MCPServerServiceCredentialDB).where(
            MCPServerServiceCredentialDB.mcp_server_id == server_id
        )
        await self.db.execute(stmt)
        await self.db.flush()

    async def set_credential_config(
        self,
        server: MCPServerDB,
        *,
        scope: MCPCredentialScope,
        personal_header_names: list[str],
    ) -> None:
        server.credential_scope = scope
        server.personal_header_names = personal_header_names
        self.db.add(server)
        await self.db.flush()

    async def get_user_credential(self, server_id: UUID, user_id: UUID) -> str | None:
        """One user's decrypted secret for a personal server, if entered."""
        stmt = select(MCPServerUserCredentialDB.credentials_encrypted).where(
            MCPServerUserCredentialDB.mcp_server_id == server_id,
            MCPServerUserCredentialDB.user_id == user_id,
        )
        encrypted = (await self.db.execute(stmt)).scalar_one_or_none()
        return decrypt_value(encrypted) if encrypted is not None else None

    async def set_user_credential(
        self, server_id: UUID, user_id: UUID, plaintext: str
    ) -> None:
        stmt = select(MCPServerUserCredentialDB).where(
            MCPServerUserCredentialDB.mcp_server_id == server_id,
            MCPServerUserCredentialDB.user_id == user_id,
        )
        row = (await self.db.execute(stmt)).scalar_one_or_none()
        if row is None:
            row = MCPServerUserCredentialDB(
                mcp_server_id=server_id,
                user_id=user_id,
                credentials_encrypted=encrypt_value(plaintext),
            )
        else:
            row.credentials_encrypted = encrypt_value(plaintext)
        self.db.add(row)
        await self.db.flush()

    async def delete_user_credential(self, server_id: UUID, user_id: UUID) -> bool:
        stmt = delete(MCPServerUserCredentialDB).where(
            MCPServerUserCredentialDB.mcp_server_id == server_id,
            MCPServerUserCredentialDB.user_id == user_id,
        )
        result = await self.db.execute(stmt)
        await self.db.flush()
        return bool(result.rowcount)

    async def delete_user_credentials(self, server_id: UUID) -> int:
        """Drop every user's secret for a server, returning how many."""
        stmt = delete(MCPServerUserCredentialDB).where(
            MCPServerUserCredentialDB.mcp_server_id == server_id
        )
        result = await self.db.execute(stmt)
        await self.db.flush()
        return int(result.rowcount or 0)

    async def list_user_credential_user_ids(self, server_id: UUID) -> list[UUID]:
        stmt = select(MCPServerUserCredentialDB.user_id).where(
            MCPServerUserCredentialDB.mcp_server_id == server_id
        )
        return list((await self.db.execute(stmt)).scalars().all())

    async def user_credential_server_ids(
        self, user_id: UUID, server_ids: Collection[UUID] | None = None
    ) -> set[UUID]:
        """The servers (in this workspace) a user has entered a secret for,
        optionally narrowed to ``server_ids``."""
        if server_ids is not None and not server_ids:
            return set()
        stmt = self._scope(
            select(MCPServerUserCredentialDB.mcp_server_id)
            .join(
                MCPServerDB,
                MCPServerDB.id == MCPServerUserCredentialDB.mcp_server_id,
            )
            .where(MCPServerUserCredentialDB.user_id == user_id)
        )
        if server_ids is not None:
            stmt = stmt.where(MCPServerUserCredentialDB.mcp_server_id.in_(server_ids))
        return set((await self.db.execute(stmt)).scalars().all())

    async def count_by_url(self) -> dict[str, int]:
        """Count configured instances per catalog endpoint in this workspace."""
        stmt = select(MCPServerDB.url, func.count(MCPServerDB.id)).group_by(
            MCPServerDB.url
        )
        if self.workspace_id is not None:
            stmt = stmt.where(MCPServerDB.workspace_id == self.workspace_id)
        result = await self.db.execute(stmt)
        return dict(result.all())

    async def list_bound_agents(self, server_id: UUID) -> list[AgentDB]:
        stmt = (
            select(AgentDB)
            .join(
                AgentMCPServerDB,
                AgentMCPServerDB.agent_id == AgentDB.id,
            )
            .where(AgentMCPServerDB.mcp_server_id == server_id)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())
