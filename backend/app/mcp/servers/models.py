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


class ServiceCredentialProvider(str, enum.Enum):
    google_service_account = "google_service_account"
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


# The official server catalog used to live here as `official_mcp_servers`. It is
# now a CDN-hosted YAML file — see app/mcp/servers/catalog.py.
