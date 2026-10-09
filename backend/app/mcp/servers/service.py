from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import Depends
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.core.repository import AgentRepository
from app.database import get_db
from app.exceptions import (
    DomainValidationError,
    NotFoundError,
)
from app.mcp.client.connectivity import (
    build_oauth_provider,
    connect_to_server,
    initiate_oauth,
    is_authorized,
)
from app.mcp.client.exceptions import OAuthAuthorizationRequired
from app.mcp.client.service_credentials import validate_service_credential
from app.mcp.client.storage import TokenStorageFactory
from app.mcp.servers import catalog as mcp_catalog
from app.mcp.servers.models import MCPAuthType, MCPServerDB, MCPServerImageDB
from app.mcp.servers.repository import MCPServerRepository
from app.mcp.servers.schemas import (
    AuthorizationRequired,
    MCPCatalogSyncResponse,
    MCPServerConnectionResponse,
    MCPServerCreate,
    MCPServerPatch,
    MCPServerResponse,
    MCPToolInfo,
    OAuthSecretHint,
    OfficialMCPServerResponse,
    ToolsListed,
)
from app.service import BaseService
from app.teams.repository import TeamRepository
from app.users.models import UserDB
from app.users.repository import UserRepository
from app.utils.encryption import decrypt_value
from app.utils.images import ProcessedImage
from app.visibility import (
    ResourceVisibility,
    audience_contains,
    is_resource_visible,
    is_resource_visible_to_identity,
    validate_visibility,
)
from app.workspaces.dependencies import get_active_workspace_id
from app.workspaces.models import WorkspaceRole
from app.workspaces.repository import WorkspaceRepository


logger = logging.getLogger(__name__)


class MCPServerService(BaseService[MCPServerDB, MCPServerRepository]):
    not_found_message = "MCP server not found"

    def __init__(self, db: AsyncSession, workspace_id: UUID | None = None):
        super().__init__(db, MCPServerRepository(db, workspace_id))
        self.workspace_id = workspace_id
        self.workspaces = WorkspaceRepository(db)
        self.teams = TeamRepository(db)

    async def get_scoped(self, server_id: UUID) -> MCPServerDB:
        server = await self.repository.get_scoped(server_id)
        if server is None:
            raise NotFoundError(self.not_found_message)
        return server

    async def get_scoped_for_update(self, server_id: UUID) -> MCPServerDB:
        server = await self.repository.get_scoped_for_update(server_id)
        if server is None:
            raise NotFoundError(self.not_found_message)
        return server

    async def get_image(self, server_id: UUID) -> MCPServerImageDB:
        await self.get_scoped(server_id)
        image = await self.repository.get_image(server_id)
        if image is None:
            raise NotFoundError("MCP server image not found")
        return image

    async def set_image(self, server_id: UUID, image: ProcessedImage) -> UUID:
        await self.get_scoped(server_id)
        revision = uuid4()
        await self.repository.set_image(
            server_id,
            data=image.data,
            media_type=image.media_type,
            sha256=image.sha256,
            revision=revision,
        )
        return revision

    async def delete_image(self, server_id: UUID) -> None:
        await self.get_scoped(server_id)
        await self.repository.delete_image(server_id)

    async def create(self, data: MCPServerCreate, owner_id: UUID) -> MCPServerDB:
        if data.auth_type == MCPAuthType.api_key and not data.api_key:
            raise DomainValidationError(
                "API key is required when auth_type is 'api_key'"
            )
        service_credential = None
        service_provider = data.service_credential_provider
        service_credentials_json = data.service_credentials_json
        if data.auth_type == MCPAuthType.service_identity:
            if not service_provider or not service_credentials_json:
                raise DomainValidationError(
                    "A credential provider and credentials are required for "
                    "service-identity auth"
                )
            service_credential = validate_service_credential(
                service_provider,
                service_credentials_json,
                data.service_credential_scopes,
            )

        await self._validate_team_ids(data.team_ids)
        validate_visibility(data.visibility, data.team_ids)
        db_server = await self.repository.create(data, owner_id)
        if data.team_ids:
            await self.repository.set_team_ids(db_server.id, data.team_ids)

        if data.auth_type == MCPAuthType.api_key and data.api_key:
            await self.repository.create_or_update_api_key(db_server.id, data.api_key)

        if (
            data.auth_type == MCPAuthType.oauth2
            and data.oauth_client_id
            and data.oauth_client_secret
        ):
            await self.repository.create_or_update_oauth_credentials(
                db_server.id,
                data.oauth_client_id,
                data.oauth_client_secret,
                data.oauth_token_endpoint_auth_method,
            )
        if service_credential is not None:
            assert service_provider is not None and service_credentials_json is not None
            await self.repository.create_or_update_service_credential(
                db_server.id,
                provider=service_provider,
                credentials_json=service_credentials_json,
                scopes=service_credential.scopes,
                principal=service_credential.principal,
            )

        return db_server

    async def get(self, server_id: UUID) -> MCPServerDB:
        return await self.get_scoped(server_id)

    async def get_visible(self, server_id: UUID, user: UserDB) -> MCPServerDB:
        server = await self.get_scoped(server_id)
        team_ids = (
            set(await self.repository.list_team_ids(server.id))
            if server.visibility == ResourceVisibility.teams
            else set()
        )
        if not is_resource_visible(
            visibility=server.visibility,
            owner_id=server.owner_id,
            team_ids=team_ids,
            user=user,
        ):
            raise NotFoundError(self.not_found_message)
        return server

    async def _validate_team_ids(self, team_ids: list[UUID]) -> None:
        if self.workspace_id is None:
            raise RuntimeError("workspace_id is required")
        for team_id in set(team_ids):
            if (
                await self.teams.get_in_workspace_for_key_share(
                    team_id, self.workspace_id
                )
                is None
            ):
                raise DomainValidationError("Team not found in workspace")

    async def to_response(self, server: MCPServerDB) -> MCPServerResponse:
        """Project a server to its API response, enriching OAuth2 servers with
        their static client_id (the client secret is never exposed)."""
        oauth_client_id = None
        if server.auth_type == MCPAuthType.oauth2:
            creds = await self.repository.get_oauth_credentials(server.id)
            oauth_client_id = creds.client_id if creds else None
        service_creds = (
            await self.repository.get_service_credential(server.id)
            if server.auth_type == MCPAuthType.service_identity
            else None
        )
        team_ids = (
            await self.repository.list_team_ids(server.id)
            if server.visibility == ResourceVisibility.teams
            else []
        )
        return MCPServerResponse(
            **server.model_dump(),
            oauth_client_id=oauth_client_id,
            service_credential_provider=(
                service_creds.provider if service_creds else None
            ),
            service_credential_principal=(
                service_creds.principal if service_creds else None
            ),
            service_credential_scopes=(service_creds.scopes if service_creds else []),
            team_ids=team_ids,
        )

    async def get_oauth_secret_hint(self, server_id: UUID) -> OAuthSecretHint:
        """Return a non-reversible hint (last 4 chars + length) about the stored
        OAuth client secret. Requires decrypting the secret, so the endpoint that
        exposes this is admin-gated."""
        await self.get_scoped(server_id)
        creds = await self.repository.get_oauth_credentials(server_id)
        if not creds:
            return OAuthSecretHint(is_set=False)
        secret = decrypt_value(creds.client_secret_encrypted)
        # Only reveal the last 4 for secrets long enough that it stays a small
        # fraction of the value; short secrets return length only.
        last4 = secret[-4:] if len(secret) >= 10 else None
        return OAuthSecretHint(is_set=True, last4=last4, length=len(secret))

    async def list_responses(self, user: UserDB) -> list[MCPServerResponse]:
        rows = await self.repository.list_with_credential_metadata()
        team_ids = await self.repository.list_team_ids_for_servers(
            [
                server.id
                for server, *_ in rows
                if server.visibility == ResourceVisibility.teams
            ]
        )
        # Gate client_id on the current auth type (as to_response does): a server
        # switched away from OAuth2 may still have a stale credentials row.
        return [
            MCPServerResponse(
                **server.model_dump(),
                team_ids=team_ids.get(server.id, []),
                oauth_client_id=(
                    client_id if server.auth_type == MCPAuthType.oauth2 else None
                ),
                service_credential_provider=(
                    service_provider
                    if server.auth_type == MCPAuthType.service_identity
                    else None
                ),
                service_credential_principal=(
                    service_principal
                    if server.auth_type == MCPAuthType.service_identity
                    else None
                ),
                service_credential_scopes=(
                    service_scopes or []
                    if server.auth_type == MCPAuthType.service_identity
                    else []
                ),
            )
            for (
                server,
                client_id,
                service_provider,
                service_principal,
                service_scopes,
            ) in rows
            if is_resource_visible(
                visibility=server.visibility,
                owner_id=server.owner_id,
                team_ids=set(team_ids.get(server.id, [])),
                user=user,
            )
        ]

    async def update(self, server_id: UUID, data: MCPServerPatch) -> MCPServerDB:
        server = await self.repository.get_scoped_for_update(server_id)
        if server is None:
            raise NotFoundError(self.not_found_message)
        next_visibility = data.visibility or server.visibility
        next_team_ids = (
            data.team_ids
            if data.team_ids is not None
            else (
                await self.repository.list_team_ids(server_id)
                if server.visibility == ResourceVisibility.teams
                else []
            )
        )
        await self._validate_team_ids(next_team_ids)
        validate_visibility(next_visibility, next_team_ids)
        if data.visibility is not None or data.team_ids is not None:
            agents = AgentRepository(self.db, self.workspace_id)
            for agent in await self.repository.list_bound_agents(server_id):
                if not audience_contains(
                    parent_visibility=agent.visibility,
                    parent_owner_id=agent.owner_id,
                    parent_team_ids=(
                        set(await agents.get_team_ids(agent.id))
                        if agent.visibility == ResourceVisibility.teams
                        else set()
                    ),
                    child_visibility=next_visibility,
                    child_owner_id=server.owner_id,
                    child_team_ids=set(next_team_ids),
                ):
                    raise DomainValidationError(
                        f"MCP server scope is incompatible with agent '{agent.name}'"
                    )
                if self.workspace_id is not None:
                    for grant in await agents.get_permissions(agent.id):
                        membership = await self.workspaces.get_membership(
                            self.workspace_id, grant.user_id
                        )
                        if (
                            membership is not None
                            and not is_resource_visible_to_identity(
                                visibility=next_visibility,
                                owner_id=server.owner_id,
                                team_ids=set(next_team_ids),
                                user_id=grant.user_id,
                                is_admin=membership.role == WorkspaceRole.admin,
                                team_id=membership.team_id,
                            )
                        ):
                            raise DomainValidationError(
                                "MCP server scope excludes an explicitly granted "
                                f"user of agent '{agent.name}'"
                            )
        previous_auth_type = server.auth_type
        # Credential fields are excluded from serialization, so repository.update
        # only touches the mcp_servers row; secrets are persisted separately.
        updated = await self.repository.update(server, data)
        if data.team_ids is not None:
            await self.repository.set_team_ids(server_id, data.team_ids)
        if updated.auth_type != previous_auth_type:
            if previous_auth_type == MCPAuthType.api_key:
                await self.repository.delete_credentials(server_id, api_key=True)
            elif previous_auth_type == MCPAuthType.oauth2:
                await self.repository.delete_credentials(server_id, api_key=False)
            elif previous_auth_type == MCPAuthType.service_identity:
                await self.repository.delete_service_credential(server_id)

        if data.api_key:
            await self.repository.create_or_update_api_key(server_id, data.api_key)

        # Partial: editing client_id (or the token-endpoint auth method) alone
        # patches it while a blank secret keeps the stored one (the client secret
        # is write-only in the UI).
        if (
            data.oauth_client_id
            or data.oauth_client_secret
            or data.oauth_token_endpoint_auth_method
        ):
            await self.repository.update_oauth_credentials(
                server_id,
                client_id=data.oauth_client_id or None,
                client_secret=data.oauth_client_secret or None,
                auth_method=data.oauth_token_endpoint_auth_method or None,
            )

        service_fields_changed = (
            data.service_credential_provider is not None
            or data.service_credentials_json is not None
            or data.service_credential_scopes is not None
        )
        if updated.auth_type == MCPAuthType.service_identity and (
            service_fields_changed or previous_auth_type != MCPAuthType.service_identity
        ):
            existing = await self.repository.get_service_credential(server_id)
            provider = data.service_credential_provider or (
                existing.provider if existing else None
            )
            credentials_json = data.service_credentials_json or (
                decrypt_value(existing.credentials_encrypted) if existing else None
            )
            scopes = (
                data.service_credential_scopes
                if data.service_credential_scopes is not None
                else (existing.scopes if existing else [])
            )
            if provider is None or credentials_json is None:
                raise DomainValidationError(
                    "A credential provider and credentials are required for "
                    "service-identity auth"
                )
            validated = validate_service_credential(provider, credentials_json, scopes)
            await self.repository.create_or_update_service_credential(
                server_id,
                provider=provider,
                credentials_json=credentials_json,
                scopes=validated.scopes,
                principal=validated.principal,
            )

        return updated

    async def purge_invalidated_state(
        self,
        server_id: UUID,
        updated: MCPServerDB,
        previous_auth_type: MCPAuthType,
        previous_url: str,
        oauth_credentials_changed: bool = False,
    ) -> None:
        """Drop stored state the edit has just made meaningless.

        Two triggers, with deliberately different blast radii (design review
        §5.8 — this used to do nothing at all, orphaning credential rows and
        leaving every user holding tokens minted for the old resource):

        * **URL changed** — every per-user Redis artefact was issued *for the
          old resource*: access and refresh tokens, the DCR client registration,
          the cached authorization-server metadata. None of it is valid against
          a different URL, and a stale refresh token is worse than none because
          `is_authorized` will keep reporting the user as connected.
          Admin-entered credential rows are **kept**: a static client id/secret
          is configuration the admin typed, and an admin re-pointing a server at
          a new path of the same provider must not silently lose it.
        * **Auth type changed** — the same Redis purge. The credential row for
          the scheme being left is deleted inside the database transaction by
          :meth:`update`, before this post-commit cleanup runs.
        * **Static OAuth credentials changed** — tokens and a previous dynamic
          client registration belong to a different OAuth application.

        Redis purging is best-effort: a cache that is down must not fail the
        edit. The cost of a miss is a stale token, which the next authorization
        overwrites anyway.
        """
        auth_type_changed = updated.auth_type != previous_auth_type
        if (
            not auth_type_changed
            and updated.url == previous_url
            and not oauth_credentials_changed
        ):
            return

        try:
            if self.workspace_id is None:
                raise RuntimeError("workspace_id is required")
            deleted = await TokenStorageFactory().clear_server_data(
                str(self.workspace_id), str(server_id)
            )
        except Exception:  # noqa: BLE001 — a cache outage must not fail the edit
            logger.warning(
                "Could not purge stored authorization state for MCP server %s after "
                "an edit; users may need to reconnect manually",
                server_id,
                exc_info=True,
            )
            return
        if deleted:
            logger.info(
                "Purged %s stored Redis keys for MCP server %s after an auth-type/URL "
                "change; affected users must reconnect",
                deleted,
                server_id,
            )

    async def purge_server_data(self, server_id: UUID) -> None:
        """Best-effort removal of Redis authorization state after DB deletion."""
        try:
            if self.workspace_id is None:
                raise RuntimeError("workspace_id is required")
            await TokenStorageFactory().clear_server_data(
                str(self.workspace_id), str(server_id)
            )
        except Exception:  # noqa: BLE001 — the committed delete must stay successful
            logger.warning(
                "Could not purge stored authorization state for deleted MCP server %s",
                server_id,
                exc_info=True,
            )

    async def delete(self, server_id: UUID) -> None:
        """Delete the server row. Refused while agents are bound: the binding
        FK has no cascade, so the flush fails and surfaces as a clean 400.
        Detaching first is the agents module's job — the router composes
        `AgentMCPServerService.detach_server` before this when the dialog's
        explicit confirm asks for it (#369)."""
        server = await self.get_scoped_for_update(server_id)
        try:
            await self.repository.delete(server)
        except IntegrityError as exc:
            raise DomainValidationError(
                "MCP server is used by agents — detach it first"
            ) from exc

    async def list_official(self) -> list[OfficialMCPServerResponse]:
        """Return catalog templates with their workspace instance counts."""
        catalog = await mcp_catalog.get_catalog()
        installed_counts = await self.repository.count_by_url()
        return [
            OfficialMCPServerResponse(
                **entry.model_dump(),
                is_installed=installed_counts.get(entry.url, 0) > 0,
                installed_count=installed_counts.get(entry.url, 0),
            )
            for entry in catalog
        ]

    @staticmethod
    async def sync_catalog() -> MCPCatalogSyncResponse:
        return MCPCatalogSyncResponse(**await mcp_catalog.sync_catalog())

    async def reset(self, server_id: UUID) -> dict:
        await self.get(server_id)
        if self.workspace_id is None:
            raise RuntimeError("workspace_id is required")
        factory = TokenStorageFactory()
        deleted = await factory.clear_server_data(
            str(self.workspace_id), str(server_id)
        )
        return {"deleted_keys": deleted}

    async def list_connections(
        self, server_id: UUID
    ) -> list[MCPServerConnectionResponse]:
        """Users holding a stored OAuth token for the server, with a coarse
        token status: ``expired`` when the access token is past its expiry and
        no refresh token can renew it, ``active`` otherwise."""
        await self.get(server_id)
        if self.workspace_id is None:
            raise RuntimeError("workspace_id is required")
        factory = TokenStorageFactory()

        user_ids: list[UUID] = []
        for raw_id in await factory.list_connected_user_ids(
            str(self.workspace_id), str(server_id)
        ):
            try:
                user_ids.append(UUID(raw_id))
            except ValueError:
                continue

        if self.workspace_id is not None:
            user_ids = [
                user_id
                for user_id in user_ids
                if await self.workspaces.get_membership(self.workspace_id, user_id)
                is not None
            ]
        users = await UserRepository(self.db).list_by_ids(user_ids)
        users_by_id = {user.id: user for user in users}

        connections: list[MCPServerConnectionResponse] = []
        for user_id in user_ids:
            stored = await factory.get_storage(
                str(self.workspace_id), str(user_id), str(server_id)
            ).get_stored_token()
            if not stored:
                continue
            expired = (
                stored.expires_at is not None
                and stored.expires_at <= datetime.now(UTC)
                and not stored.token_payload.refresh_token
            )
            # Deleted users may still hold tokens — keep them listed (name and
            # email None) so an admin can revoke the orphaned connection.
            user = users_by_id.get(user_id)
            connections.append(
                MCPServerConnectionResponse(
                    user_id=user_id,
                    name=user.name if user else None,
                    email=user.email if user else None,
                    picture_url=user.picture_url if user else None,
                    image_revision=user.image_revision if user else None,
                    status="expired" if expired else "active",
                )
            )

        connections.sort(key=lambda c: (c.name or c.email or str(c.user_id)).lower())
        return connections

    async def delete_connection(self, server_id: UUID, user_id: UUID) -> dict:
        """Revoke one user's connection: clear their stored tokens, client
        info and OAuth metadata for the server. The user re-authenticates on
        their next use."""
        await self.get(server_id)
        if self.workspace_id is None:
            raise RuntimeError("workspace_id is required")
        if (
            self.workspace_id is not None
            and await self.workspaces.get_membership(self.workspace_id, user_id) is None
        ):
            raise NotFoundError("User not found")
        factory = TokenStorageFactory()
        deleted = await factory.clear_user_server_data(
            str(self.workspace_id), str(user_id), str(server_id)
        )
        return {"deleted_keys": deleted}

    async def handle_oauth_callback(self, code: str, state: str, user_id: UUID) -> dict:
        storage_factory = TokenStorageFactory()
        result = await storage_factory.get_storage_from_state(state)

        if not result:
            raise DomainValidationError("Invalid or expired OAuth state")

        storage, state_data = result
        if (
            self.workspace_id is None
            or state_data.workspace_id != str(self.workspace_id)
            or state_data.user_id != str(user_id)
        ):
            raise NotFoundError("MCP server not found")

        mcp_server = await self.repository.get_scoped(state_data.mcp_server_id)
        if not mcp_server:
            raise NotFoundError("MCP server not found")

        provider = await build_oauth_provider(mcp_server, storage, self.repository)
        # The provider loads its stored state and applies the per-provider
        # OAuth quirks (`OAUTH_QUIRKS` in `client/auth.py`) itself, including
        # the token-endpoint auth method this exchange needs.
        await provider.manual_exchange(code, state)

        return {
            "status": "success",
            "message": "Authorization code received and published",
        }

    async def list_tools(
        self, server: MCPServerDB, user_id: str
    ) -> ToolsListed | AuthorizationRequired:
        """This user's tools for `server`, or the authorize URL they need first.

        Both are ordinary answers, so both are ordinary return values: needing
        OAuth is the expected state of a server nobody has connected yet. It
        used to raise, and an app-global handler turned the exception into the
        response — which meant *any* endpoint touching MCP could answer 401
        with an auth URL, whether or not connecting was its job (§2.4).
        """
        try:
            if self.workspace_id is None:
                raise RuntimeError("workspace_id is required")
            if server.auth_type == MCPAuthType.oauth2 and not await is_authorized(
                server, user_id, self.workspace_id
            ):
                # Not connected: discover OAuth metadata, which ends in
                # OAuthAuthorizationRequired carrying the authorize URL. No
                # business tool is called.
                await initiate_oauth(server, user_id, self.workspace_id, self.db)

            async with connect_to_server(
                server, user_id, self.workspace_id, self.db
            ) as client:
                tools = await client.list_tools()
                return ToolsListed(
                    tools=[
                        MCPToolInfo(name=tool.name, description=tool.description)
                        for tool in tools
                    ]
                )
        except OAuthAuthorizationRequired as exc:
            # Also catches the *implicit* 401 — a stored token that the server
            # has since revoked only fails during the handshake, and the seam
            # unwraps it out of the client's connect failure for us.
            return AuthorizationRequired(auth_url=exc.url)


def get_mcp_server_service(
    db: AsyncSession = Depends(get_db),
    workspace_id: UUID = Depends(get_active_workspace_id),
) -> MCPServerService:
    return MCPServerService(db, workspace_id)
