import enum
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Column, Enum, Field, SQLModel

from app.models import BaseDBModel
from app.visibility import ResourceVisibility


class MCPAuthType(str, enum.Enum):
    none = "none"
    api_key = "api_key"
    oauth2 = "oauth2"
    service_identity = "service_identity"
    custom_http = "custom_http"


class MCPCredentialScope(str, enum.Enum):
    """Who supplies a server's secret: the admin once, or every user."""

    shared = "shared"
    personal = "personal"


# Auth types whose secret is a static value an admin can either share with the
# whole audience or leave for each user to enter. OAuth is always personal;
# `none` and `service_identity` are always shared.
USER_ENTERED_AUTH_TYPES = frozenset({MCPAuthType.api_key, MCPAuthType.custom_http})


def stores_user_credentials(auth_type: MCPAuthType, scope: MCPCredentialScope) -> bool:
    """Each user's own API key or header values, stored in Postgres."""
    return scope == MCPCredentialScope.personal and auth_type in USER_ENTERED_AUTH_TYPES


def is_personal_auth(auth_type: MCPAuthType, scope: MCPCredentialScope) -> bool:
    """Every user authenticates with their own account or secret."""
    return auth_type == MCPAuthType.oauth2 or stores_user_credentials(auth_type, scope)


def credential_scope_for(
    auth_type: MCPAuthType, requested: MCPCredentialScope
) -> MCPCredentialScope:
    """The scope an auth type actually gets: OAuth is always personal, and only
    API-key and custom HTTP servers can be either."""
    if auth_type == MCPAuthType.oauth2:
        return MCPCredentialScope.personal
    if auth_type in USER_ENTERED_AUTH_TYPES:
        return requested
    return MCPCredentialScope.shared


class ServiceCredentialProvider(str, enum.Enum):
    google_service_account = "google_service_account"
    oauth_client_credentials = "oauth_client_credentials"
    github_app = "github_app"
    aws_iam = "aws_iam"
    azure_managed_identity = "azure_managed_identity"
    custom_http_headers = "custom_http_headers"


class MCPServerBase(SQLModel):
    workspace_id: UUID = Field(foreign_key="workspaces.id", nullable=False, index=True)
    name: str = Field(nullable=False)
    url: str = Field(nullable=False)
    auth_type: MCPAuthType = Field(default=MCPAuthType.none)
    icon_url: str | None = Field(default=None)
    description: str | None = Field(default=None)
    group: str | None = Field(default=None, max_length=255, nullable=True, index=True)


class MCPServerDB(MCPServerBase, BaseDBModel, table=True):
    __tablename__ = "mcp_servers"

    url: str = Field(nullable=False)
    auth_type: MCPAuthType = Field(
        default=MCPAuthType.none,
        sa_column=Column(Enum(MCPAuthType, name="mcp_auth_type"), nullable=False),
    )
    credential_scope: MCPCredentialScope = Field(
        default=MCPCredentialScope.shared,
        sa_column=Column(
            Enum(MCPCredentialScope, native_enum=False, create_constraint=False),
            nullable=False,
            server_default=MCPCredentialScope.shared.value,
        ),
    )
    # Header names each user fills in for a personal custom HTTP server.
    personal_header_names: list[str] = Field(
        default_factory=list,
        sa_column=Column(JSONB, nullable=False, server_default=sa.text("'[]'")),
    )
    image_revision: UUID | None = Field(default=None, nullable=True)
    owner_id: UUID = Field(
        foreign_key="users.id", ondelete="CASCADE", nullable=False, index=True
    )
    visibility: ResourceVisibility = Field(
        default=ResourceVisibility.workspace,
        sa_column=Column(
            Enum(ResourceVisibility, native_enum=False, create_constraint=False),
            nullable=False,
            server_default=ResourceVisibility.workspace.value,
        ),
    )
    disabled_tools: list[str] = Field(
        default_factory=list,
        sa_column=Column(
            JSONB,
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )
    # Managed servers are materialized by an internal control plane. Their
    # transport/auth fields cannot be edited through the generic MCP routes.
    managed_by: str | None = Field(default=None, max_length=50, index=True)
    managed_resource_id: UUID | None = Field(default=None, index=True)

    @property
    def is_personal(self) -> bool:
        return is_personal_auth(self.auth_type, self.credential_scope)

    @property
    def uses_user_credentials(self) -> bool:
        return stores_user_credentials(self.auth_type, self.credential_scope)


class MCPServerTeamDB(BaseDBModel, table=True):
    __tablename__ = "mcp_server_teams"
    __table_args__ = (
        sa.UniqueConstraint(
            "mcp_server_id", "team_id", name="uq_mcp_server_visibility_team"
        ),
    )

    mcp_server_id: UUID = Field(
        foreign_key="mcp_servers.id", ondelete="CASCADE", nullable=False, index=True
    )
    team_id: UUID = Field(
        foreign_key="teams.id", ondelete="CASCADE", nullable=False, index=True
    )


class MCPServerImageDB(BaseDBModel, table=True):
    __tablename__ = "mcp_server_images"
    __table_args__ = (
        sa.UniqueConstraint("mcp_server_id", name="uq_mcp_server_image_server_id"),
    )

    mcp_server_id: UUID = Field(
        foreign_key="mcp_servers.id",
        ondelete="CASCADE",
        nullable=False,
        index=True,
    )
    data: bytes = Field(sa_column=Column(sa.LargeBinary, nullable=False))
    media_type: str = Field(max_length=50, nullable=False)
    sha256: str = Field(max_length=64, nullable=False)


class MCPServerAPIKeyDB(BaseDBModel, table=True):
    __tablename__ = "mcp_server_api_keys"

    mcp_server_id: UUID = Field(foreign_key="mcp_servers.id", nullable=False)
    key_encrypted: str = Field(sa_column=Column(sa.Text, nullable=False))
    created_by: UUID | None = Field(default=None, foreign_key="users.id")


class MCPServerOAuthCredentialsDB(BaseDBModel, table=True):
    __tablename__ = "mcp_server_oauth_credentials"

    mcp_server_id: UUID = Field(
        foreign_key="mcp_servers.id", nullable=False, unique=True
    )
    client_id: str = Field(nullable=False)
    client_secret_encrypted: str = Field(sa_column=Column(sa.Text, nullable=False))
    token_endpoint_auth_method: str | None = Field(default=None)
    created_by: UUID | None = Field(default=None, foreign_key="users.id")


class MCPServerServiceCredentialDB(BaseDBModel, table=True):
    """Encrypted machine identity shared by every caller of one MCP server."""

    __tablename__ = "mcp_server_service_credentials"

    mcp_server_id: UUID = Field(
        foreign_key="mcp_servers.id",
        ondelete="CASCADE",
        nullable=False,
        unique=True,
    )
    provider: ServiceCredentialProvider = Field(
        sa_column=Column(
            Enum(
                ServiceCredentialProvider,
                native_enum=False,
                create_constraint=False,
            ),
            nullable=False,
        )
    )
    credentials_encrypted: str = Field(sa_column=Column(sa.Text, nullable=False))
    scopes: list[str] = Field(
        default_factory=list,
        sa_column=Column(JSONB, nullable=False, server_default=sa.text("'[]'")),
    )
    principal: str | None = Field(default=None)
    created_by: UUID | None = Field(default=None, foreign_key="users.id")


class MCPServerUserCredentialDB(BaseDBModel, table=True):
    """One user's own secret for a personal API-key or custom HTTP server.

    ``credentials_encrypted`` holds the raw API key for ``api_key`` servers and
    the ``custom_http_headers`` JSON document for ``custom_http`` servers.
    """

    __tablename__ = "mcp_server_user_credentials"
    __table_args__ = (
        sa.UniqueConstraint(
            "mcp_server_id", "user_id", name="uq_mcp_server_user_credential"
        ),
    )

    mcp_server_id: UUID = Field(
        foreign_key="mcp_servers.id", ondelete="CASCADE", nullable=False, index=True
    )
    user_id: UUID = Field(
        foreign_key="users.id", ondelete="CASCADE", nullable=False, index=True
    )
    credentials_encrypted: str = Field(sa_column=Column(sa.Text, nullable=False))


# The official server catalog used to live here as `official_mcp_servers`. It is
# now a CDN-hosted YAML file — see app/mcp/servers/catalog.py.
