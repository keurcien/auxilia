from datetime import datetime
from typing import Literal
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


class OfficialMCPServerResponse(SQLModel):
    """One catalog entry (see mcp/servers/catalog.py). Deliberately NOT an
    MCPServerResponse: catalog entries come from a file, so they have no id and
    no timestamps — ``url`` is their identity."""

    name: str
    url: str
    auth_type: MCPAuthType
    icon_url: str | None = None
    description: str | None = None
    # Whether a workspace server already exists for this url.
    is_installed: bool = Field(default=False)
    supports_dcr: bool | None = Field(default=None)


class MCPCatalogSyncResponse(SQLModel):
    """Diff returned by the admin catalog sync. ``added``/``removed`` list urls."""

    added: list[str]
    removed: list[str]
    server_count: int
    fetched_at: datetime


class MCPServerAgentResponse(SQLModel):
    """An agent still bound to an MCP server — shown in the delete-guard dialog."""

    id: UUID
    name: str
    emoji: str | None = None
    color: str | None = None


class OAuthSecretHint(SQLModel):
    """Non-reversible hint about the stored OAuth client secret, so an admin can
    confirm *which* secret is configured without exposing it. Admin-only."""

    is_set: bool = False
    last4: str | None = None
    length: int | None = None


class MCPServerConnectionResponse(SQLModel):
    """A user's stored OAuth connection to an MCP server (admin view).

    ``expired`` means the access token is past its expiry with no refresh
    token to renew it — runs using this connection will fail until the user
    re-authenticates.
    """

    user_id: UUID
    name: str | None = None
    email: str | None = None
    picture_url: str | None = None
    status: Literal["active", "expired"] = "active"


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
