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
    name: str = Field(nullable=False)
    url: str = Field(nullable=False)
    auth_type: MCPAuthType = Field(default=MCPAuthType.none)
    icon_url: str | None = Field(default=None)
    description: str | None = Field(default=None)


class MCPServerDB(MCPServerBase, BaseDBModel, table=True):
    __tablename__ = "mcp_servers"

    url: str = Field(nullable=False, unique=True)
    auth_type: MCPAuthType = Field(
        default=MCPAuthType.none, sa_column=Column(Enum(MCPAuthType), nullable=False)
    )


class MCPServerAPIKeyDB(BaseDBModel, table=True):
    __tablename__ = "mcp_server_api_keys"

    mcp_server_id: UUID = Field(foreign_key="mcp_servers.id", nullable=False)
    key_encrypted: str = Field(sa_column=Column(sa.Text, nullable=False))
    created_by: UUID | None = Field(default=None, foreign_key="users.id")


class MCPServerOAuthCredentialsDB(BaseDBModel, table=True):
    __tablename__ = "mcp_server_oauth_credentials"

    mcp_server_id: UUID = Field(foreign_key="mcp_servers.id", nullable=False, unique=True)
    client_id: str = Field(nullable=False)
    client_secret_encrypted: str = Field(sa_column=Column(sa.Text, nullable=False))
    token_endpoint_auth_method: str | None = Field(default=None)
    created_by: UUID | None = Field(default=None, foreign_key="users.id")


class OfficialMCPServerDB(MCPServerBase, BaseDBModel, table=True):
    __tablename__ = "official_mcp_servers"

    url: str = Field(nullable=False, unique=True)
    auth_type: MCPAuthType = Field(
        default=MCPAuthType.none, sa_column=Column(Enum(MCPAuthType), nullable=False)
    )
    supports_dcr: bool | None = Field(default=None)
