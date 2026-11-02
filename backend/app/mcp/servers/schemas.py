from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import field_serializer, field_validator
from sqlmodel import Field, SQLModel

from app.mcp.compatibility import OAuthRedirectMode
from app.mcp.servers.models import MCPAuthType, ServiceCredentialProvider
from app.visibility import ResourceVisibility


def _normalize_group(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = "/".join(part.strip() for part in value.split("/") if part.strip())
    if len(normalized) > 255:
        raise ValueError("group must be at most 255 characters")
    return normalized or None


class MCPServerCreate(SQLModel):
    name: str
    url: str
    auth_type: MCPAuthType = MCPAuthType.none
    icon_url: str | None = None
    description: str | None = None
    group: str | None = None
    visibility: ResourceVisibility = ResourceVisibility.workspace
    team_ids: list[UUID] = Field(default_factory=list, exclude=True)
    api_key: str | None = Field(default=None, exclude=True)
    oauth_client_id: str | None = Field(default=None, exclude=True)
    oauth_client_secret: str | None = Field(default=None, exclude=True)
    oauth_token_endpoint_auth_method: str | None = Field(default=None, exclude=True)
    service_credential_provider: ServiceCredentialProvider | None = Field(
        default=None, exclude=True
    )
    service_credentials_json: str | None = Field(default=None, exclude=True)
    service_credential_scopes: list[str] = Field(default_factory=list, exclude=True)

    @field_validator("group")
    @classmethod
    def normalize_group(cls, value: str | None) -> str | None:
        return _normalize_group(value)


class MCPServerPatch(SQLModel):
    name: str | None = None
    url: str | None = None
    auth_type: MCPAuthType | None = None
    icon_url: str | None = None
    description: str | None = None
    group: str | None = None
    visibility: ResourceVisibility | None = None
    team_ids: list[UUID] | None = Field(default=None, exclude=True)
    # Credentials are excluded from serialization so they never touch the
    # mcp_servers row (they live in separate tables); the service persists them
    # via the repository's create_or_update_* methods.
    api_key: str | None = Field(default=None, exclude=True)
    oauth_client_id: str | None = Field(default=None, exclude=True)
    oauth_client_secret: str | None = Field(default=None, exclude=True)
    oauth_token_endpoint_auth_method: str | None = Field(default=None, exclude=True)
    service_credential_provider: ServiceCredentialProvider | None = Field(
        default=None, exclude=True
    )
    service_credentials_json: str | None = Field(default=None, exclude=True)
    service_credential_scopes: list[str] | None = Field(default=None, exclude=True)
    disabled_tools: list[str] = Field(default_factory=list)

    @field_validator("group")
    @classmethod
    def normalize_group(cls, value: str | None) -> str | None:
        return _normalize_group(value)

    @property
    def clears_oauth_credentials(self) -> bool:
        """Both OAuth fields explicitly blank mean "return to DCR".

        Missing fields still mean "leave unchanged", which preserves the
        write-only secret behavior for ordinary edits.
        """
        fields = self.model_fields_set
        return (
            "oauth_client_id" in fields
            and "oauth_client_secret" in fields
            and not self.oauth_client_id
            and not self.oauth_client_secret
        )

    @property
    def changes_oauth_credentials(self) -> bool:
        return self.clears_oauth_credentials or bool(
            self.oauth_client_id
            or self.oauth_client_secret
            or self.oauth_token_endpoint_auth_method
        )


class MCPServerResponse(SQLModel):
    id: UUID
    name: str
    url: str
    auth_type: MCPAuthType
    icon_url: str | None = None
    image_revision: UUID | None = None
    description: str | None = None
    group: str | None = None
    owner_id: UUID | None = None
    visibility: ResourceVisibility = ResourceVisibility.workspace
    team_ids: list[UUID] = Field(default_factory=list)
    disabled_tools: list[str] = Field(default_factory=list)
    managed_by: str | None = None
    managed_resource_id: UUID | None = None
    managed_endpoint: str | None = None
    created_at: datetime
    updated_at: datetime
    # Static OAuth client_id when configured (public identifier, not a secret);
    # None for DCR servers. The client secret is never returned.
    oauth_client_id: str | None = None
    service_credential_provider: ServiceCredentialProvider | None = None
    service_credential_principal: str | None = None
    service_credential_scopes: list[str] = Field(default_factory=list)

    @field_serializer("managed_by")
    def serialize_managed_by(self, value: str | None) -> str | None:
        return "database" if value == "dbhub" else value


class OfficialMCPServerResponse(SQLModel):
    """One catalog entry (see mcp/servers/catalog.py). Deliberately NOT an
    MCPServerResponse: catalog entries come from a file, so they have no id and
    no timestamps. Entries are reusable templates, not singleton servers."""

    name: str
    url: str
    auth_type: MCPAuthType
    icon_url: str | None = None
    description: str | None = None
    # Kept for API compatibility; multiple configured instances are allowed.
    is_installed: bool = Field(default=False)
    installed_count: int = Field(default=0, ge=0)
    supports_dcr: bool | None = Field(default=None)
    supports_cimd: bool | None = Field(default=None)
    requires_url_configuration: bool = Field(default=False)
    custom_http_headers: list[str] = Field(default_factory=list)
    service_credential_providers: list[ServiceCredentialProvider] = Field(
        default_factory=list
    )


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
    image_revision: UUID | None = None


class OAuthSecretHint(SQLModel):
    """Non-reversible hint about the stored OAuth client secret, so an admin can
    confirm *which* secret is configured without exposing it. Admin-only."""

    is_set: bool = False
    last4: str | None = None
    length: int | None = None


class OAuthCallbackInfo(SQLModel):
    """Public redirect URI to register in a provider's OAuth application."""

    callback_url: str


class OAuthManualCallbackRequest(SQLModel):
    callback_url: str = Field(min_length=1, max_length=4096)


class OAuthManualCallbackResponse(SQLModel):
    success: bool = True
    server_id: UUID
    server_name: str


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
    image_revision: UUID | None = None
    status: Literal["active", "expired"] = "active"


class ConnectionProbeRequest(SQLModel):
    """Candidate credentials to test without saving (create/edit form)."""

    url: str
    auth_type: MCPAuthType = MCPAuthType.none
    api_key: str | None = Field(default=None, exclude=True)
    service_credential_provider: ServiceCredentialProvider | None = Field(
        default=None, exclude=True
    )
    service_credentials_json: str | None = Field(default=None, exclude=True)
    service_credential_scopes: list[str] = Field(default_factory=list, exclude=True)


class MCPToolInfo(SQLModel):
    name: str
    description: str | None = None


class ToolsListed(SQLModel):
    """The tools a server exposes to this user."""

    status: Literal["ok"] = "ok"
    tools: list[MCPToolInfo]


class AuthorizationRequired(SQLModel):
    """The user must complete OAuth at ``auth_url`` before there are any tools.

    A 200, not a 401: needing authorization is the expected answer for a server
    the user has not connected yet, and this endpoint's job is connecting.
    It used to be an exception that an app-global handler turned into a 401
    (design review §2.4).
    """

    status: Literal["auth_required"] = "auth_required"
    auth_url: str
    oauth_redirect_mode: OAuthRedirectMode = OAuthRedirectMode.hosted_callback


ListToolsResult = Annotated[
    ToolsListed | AuthorizationRequired, Field(discriminator="status")
]


class ConnectionTestResult(SQLModel):
    """Outcome of a connection test: reachability, discovered tools, and (for
    an unauthorized OAuth server) the authorize URL the client should open."""

    reachable: bool
    tool_count: int | None = None
    tool_names: list[str] | None = None
    oauth_required: bool = False
    auth_url: str | None = None
    oauth_redirect_mode: OAuthRedirectMode = OAuthRedirectMode.hosted_callback
    error: str | None = None
