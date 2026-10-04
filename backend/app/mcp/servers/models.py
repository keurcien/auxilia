import enum
from uuid import UUID

import sqlalchemy as sa
from sqlmodel import Column, Enum, Field, SQLModel

from app.models import BaseDBModel


class MCPAuthType(str, enum.Enum):
    none = "none"
    api_key = "api_key"
    oauth2 = "oauth2"


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
    __table_args__ = (
        sa.UniqueConstraint("workspace_id", "url", name="uq_mcp_server_workspace_url"),
    )

    url: str = Field(nullable=False)
    auth_type: MCPAuthType = Field(
        default=MCPAuthType.none, sa_column=Column(Enum(MCPAuthType), nullable=False)
    )
    image_revision: UUID | None = Field(default=None, nullable=True)


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


# The official server catalog used to live here as `official_mcp_servers`. It is
# now a CDN-hosted YAML file — see app/mcp/servers/catalog.py.
