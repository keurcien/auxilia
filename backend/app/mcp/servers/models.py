import enum
from datetime import datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.sql import func
from sqlmodel import Column, DateTime, Enum, Field, SQLModel


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


class MCPServerDB(MCPServerBase, table=True):
    __tablename__ = "mcp_servers"

    url: str = Field(nullable=False, unique=True)
    auth_type: MCPAuthType = Field(
        default=MCPAuthType.none, sa_column=Column(Enum(MCPAuthType), nullable=False)
    )
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    created_at: datetime = Field(
        default=None,
        sa_column=Column(
            DateTime(timezone=True), server_default=func.now(), nullable=False
        ),
    )
    updated_at: datetime = Field(
        default=None,
        sa_column=Column(
            DateTime(timezone=True),
            server_default=func.now(),
            onupdate=func.now(),
            nullable=False,
        ),
    )


class MCPServerCreate(MCPServerBase):
    api_key: str | None = Field(default=None, exclude=True)  # Not persisted to mcp_servers table
    # OAuth credentials for pre-registered OAuth clients (not DCR)
    oauth_client_id: str | None = Field(default=None, exclude=True)
    oauth_client_secret: str | None = Field(default=None, exclude=True)
    oauth_token_endpoint_auth_method: str | None = Field(default=None, exclude=True)


class MCPServerUpdate(SQLModel):
    name: str | None = None
    url: str | None = None
    auth_type: MCPAuthType | None = None
    icon_url: str | None = None
    description: str | None = None


class MCPServerRead(MCPServerBase):
    id: UUID
    created_at: datetime
    updated_at: datetime

class OfficialMCPServerRead(MCPServerRead):
    is_installed: bool = Field(default=False)
    supports_dcr: bool | None = Field(default=None)

class MCPServerAPIKeyDB(SQLModel, table=True):
    __tablename__ = "mcp_server_api_keys"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    mcp_server_id: UUID = Field(foreign_key="mcp_servers.id", nullable=False)
    key_encrypted: str = Field(sa_column=Column(sa.Text, nullable=False))
    created_by: UUID | None = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(
        default=None,
        sa_column=Column(
            DateTime(timezone=True), server_default=func.now(), nullable=False
        ),
    )
    updated_at: datetime = Field(
        default=None,
        sa_column=Column(
            DateTime(timezone=True),
            server_default=func.now(),
            onupdate=func.now(),
            nullable=False,
        ),
    )


class MCPServerOAuthCredentialsDB(SQLModel, table=True):
    __tablename__ = "mcp_server_oauth_credentials"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    mcp_server_id: UUID = Field(foreign_key="mcp_servers.id", nullable=False, unique=True)
    client_id: str = Field(nullable=False)
    client_secret_encrypted: str = Field(sa_column=Column(sa.Text, nullable=False))
    token_endpoint_auth_method: str | None = Field(default=None)
    created_by: UUID | None = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(
        default=None,
        sa_column=Column(
            DateTime(timezone=True), server_default=func.now(), nullable=False
        ),
    )
    updated_at: datetime = Field(
        default=None,
        sa_column=Column(
            DateTime(timezone=True),
            server_default=func.now(),
            onupdate=func.now(),
            nullable=False,
        ),
    )

class OfficialMCPServerDB(MCPServerBase, table=True):
    __tablename__ = "official_mcp_servers"

    url: str = Field(nullable=False, unique=True)
    auth_type: MCPAuthType = Field(
        default=MCPAuthType.none, sa_column=Column(Enum(MCPAuthType), nullable=False)
    )
    supports_dcr: bool | None = Field(default=None)
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    created_at: datetime = Field(
        default=None,
        sa_column=Column(
            DateTime(timezone=True), server_default=func.now(), nullable=False
        ),
    )
    updated_at: datetime = Field(
        default=None,
        sa_column=Column(
            DateTime(timezone=True),
            server_default=func.now(),
            onupdate=func.now(),
            nullable=False,
        ),
    )