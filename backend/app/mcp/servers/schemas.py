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
    # Credentials are excluded from serialization so they never touch the
    # mcp_servers row (they live in separate tables); the service persists them
    # via the repository's create_or_update_* methods.
    api_key: str | None = Field(default=None, exclude=True)
    oauth_client_id: str | None = Field(default=None, exclude=True)
    oauth_client_secret: str | None = Field(default=None, exclude=True)
    oauth_token_endpoint_auth_method: str | None = Field(default=None, exclude=True)


class MCPServerResponse(SQLModel):
    id: UUID
    name: str
    url: str
    auth_type: MCPAuthType
    icon_url: str | None = None
    description: str | None = None
    created_at: datetime
    updated_at: datetime
    # Static OAuth client_id when configured (public identifier, not a secret);
    # None for DCR servers. The client secret is never returned.
    oauth_client_id: str | None = None


class OfficialMCPServerResponse(MCPServerResponse):
    is_installed: bool = Field(default=False)
    supports_dcr: bool | None = Field(default=None)


class OAuthSecretHint(SQLModel):
    """Non-reversible hint about the stored OAuth client secret, so an admin can
    confirm *which* secret is configured without exposing it. Admin-only."""

    is_set: bool = False
    last4: str | None = None
    length: int | None = None


class ConnectionProbeRequest(SQLModel):
    """Candidate credentials to test without saving (create/edit form)."""

    url: str
    auth_type: MCPAuthType = MCPAuthType.none
    api_key: str | None = Field(default=None, exclude=True)


class ConnectionTestResult(SQLModel):
    """Outcome of a connection test: reachability, discovered tools, and (for
    an unauthorized OAuth server) the authorize URL the client should open."""

    reachable: bool
    tool_count: int | None = None
    tool_names: list[str] | None = None
    oauth_required: bool = False
    auth_url: str | None = None
    error: str | None = None
