from datetime import datetime
from uuid import UUID

from sqlmodel import Field, SQLModel

from app.mcp.servers.models import MCPAuthType


class MCPServerCreate(SQLModel):
    name: str
    url: str
    auth_type: MCPAuthType = MCPAuthType.none
    icon_url: str | None = None
    description: str | None = None
    api_key: str | None = Field(default=None, exclude=True)
    oauth_client_id: str | None = Field(default=None, exclude=True)
    oauth_client_secret: str | None = Field(default=None, exclude=True)
    oauth_token_endpoint_auth_method: str | None = Field(default=None, exclude=True)


class MCPServerPatch(SQLModel):
    name: str | None = None
    url: str | None = None
    auth_type: MCPAuthType | None = None
    icon_url: str | None = None
    description: str | None = None


class MCPServerResponse(SQLModel):
    id: UUID
    name: str
    url: str
    auth_type: MCPAuthType
    icon_url: str | None = None
    description: str | None = None
    created_at: datetime
    updated_at: datetime


class OfficialMCPServerResponse(MCPServerResponse):
    is_installed: bool = Field(default=False)
    supports_dcr: bool | None = Field(default=None)
