"""MCP server connectivity: provider construction, the session handshake,
authorization status, and connection testing.

Everything involved in *talking to* a remote MCP server lives here, kept out of
``MCPServerService`` (which owns CRUD and DB orchestration) so callers that only
need to open a session or check authorization don't drag in the full service.

Two distinct questions live here, deliberately kept apart:

* **authorized** (:func:`is_authorized`) — does the user hold a usable
  credential? For ``none``/``api_key`` this is always true (there is no per-user
  credential); for ``oauth2`` it means a stored token exists, optionally
  refreshed when expired. No handshake is performed.
* **reachable** (:func:`test_connection` / :func:`probe_candidate`) — does an
  actual MCP handshake succeed? This is the only real network probe.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import DomainError
from app.mcp.client.auth import WebOAuthClientProvider, build_oauth_client_metadata
from app.mcp.client.connection import open_mcp_client
from app.mcp.client.exceptions import OAuthAuthorizationRequired
from app.mcp.client.langchain_tools import list_all_mcp_tools
from app.mcp.client.storage import RedisTokenStorage, TokenStorageFactory
from app.mcp.servers.encryption import decrypt_value as decrypt_api_key
from app.mcp.servers.models import MCPAuthType, MCPServerDB
from app.mcp.servers.repository import MCPServerRepository
from app.mcp.servers.schemas import ConnectionTestResult


logger = logging.getLogger(__name__)


# --- Provider construction --------------------------------------------------


async def build_oauth_provider(
    mcp_server: MCPServerDB,
    storage: RedisTokenStorage,
    repository: MCPServerRepository | None = None,
) -> WebOAuthClientProvider:
    """Build a ``WebOAuthClientProvider`` for an OAuth2 MCP server.

    When ``repository`` is provided, static client credentials are loaded and
    decrypted (servers without them register dynamically via DCR during
    authorization). The refresh-only paths (:func:`is_authorized`) pass
    ``repository=None`` and rely on the ``client_info`` persisted to storage
    during the first authorization.

    This is the single place that turns a server into a provider; every other
    path (handshake, callback, authorization, refresh) routes through it.
    """
    client_metadata = build_oauth_client_metadata()
    client_id = client_secret = None
    if repository is not None:
        oauth_credentials = await repository.get_oauth_credentials(mcp_server.id)
        if oauth_credentials:
            client_id = oauth_credentials.client_id
            client_secret = decrypt_api_key(oauth_credentials.client_secret_encrypted)
            client_metadata.token_endpoint_auth_method = (
                oauth_credentials.token_endpoint_auth_method or "client_secret_post"
            )
    return WebOAuthClientProvider(
        server_url=mcp_server.url,
        client_metadata=client_metadata,
        storage=storage,
        client_id=client_id,
        client_secret=client_secret,
    )


# --- Connection ---------------------------------------------------------------


async def _resolve_transport_kwargs(
    mcp_server: MCPServerDB, user_id: str, db: AsyncSession
) -> dict:
    """Resolve the server's auth type to ``open_mcp_client`` keyword arguments:
    the user's OAuth provider, a Bearer ``Authorization`` header from the stored
    API key, or nothing for unauthenticated servers."""
    repository = MCPServerRepository(db)

    if mcp_server.auth_type == MCPAuthType.oauth2:
        storage = TokenStorageFactory().get_storage(user_id, str(mcp_server.id))
        provider = await build_oauth_provider(mcp_server, storage, repository)
        await provider.persist_client_info()
        return {"auth": provider}
    if mcp_server.auth_type == MCPAuthType.api_key:
        api_key = await repository.get_api_key(mcp_server.id)
        return {"headers": {"Authorization": f"Bearer {api_key}"}}
    return {}


@asynccontextmanager
async def connect_to_server(
    mcp_server: MCPServerDB,
    user_id: str,
    db: AsyncSession,
    *,
    terminate_on_close: bool = True,
):
    """Connect to an MCP server for a specific user and yield the live client.

    Callers that need the tool list call :func:`list_all_mcp_tools` on the
    yielded client themselves — the MCP App paths (read-resource / call-tool)
    never need it, so no ``tools/list`` round-trip is paid here.

    Args:
        mcp_server: MCP server configuration.
        user_id: The current user's ID.
        db: Database session (used to load credentials).
        terminate_on_close: When False, the session is NOT DELETEd on exit and is
            left to expire by the server's TTL. MCP App paths need this because
            Metabase binds artifacts (the embedded ``sessionToken``) to the MCP
            session — DELETEing it kills the token before the browser uses it.

    Yields:
        The connected MCP ``Client``.

    Raises:
        OAuthAuthorizationRequired: If OAuth authorization is needed.
        DomainError: Any other connect or in-body failure, wrapped for a clean
            client-facing message.
    """
    kwargs = await _resolve_transport_kwargs(mcp_server, user_id, db)
    async with open_mcp_client(
        mcp_server.url, terminate_on_close=terminate_on_close, **kwargs
    ) as client:
        try:
            yield client
        except (OAuthAuthorizationRequired, DomainError):
            # OAuthAuthorizationRequired: translated globally (or by
            # test_connection) into an oauth_required result, not a 500.
            raise
        except Exception as e:
            raise DomainError(str(e)) from e


# --- Authorization ----------------------------------------------------------


async def is_authorized(
    server: MCPServerDB, user_id: str, *, refresh: bool = True
) -> bool:
    """Return whether the user holds a usable credential for the server.

    ``none``/``api_key`` servers need no per-user credential and are always
    authorized. For ``oauth2``, a stored token counts; with ``refresh=True``
    (the default) an expired-but-refreshable token is refreshed and still counts.
    No handshake is performed — use :func:`test_connection` for a real probe.
    """
    if server.auth_type in (MCPAuthType.none, MCPAuthType.api_key):
        return True

    storage = TokenStorageFactory().get_storage(user_id, str(server.id))
    provider = await build_oauth_provider(server, storage)

    if refresh:
        return await provider.ensure_valid_token()

    await provider._initialize()
    tokens = await provider.context.storage.get_tokens()
    return tokens is not None


async def initiate_oauth(server: MCPServerDB, user_id: str, db: AsyncSession) -> None:
    """Build the OAuth provider and start authorization via metadata discovery.

    Raises ``OAuthAuthorizationRequired`` with the authorize URL. The run-start
    gate (``RunService``) and :func:`test_connection` / ``list_tools`` call this
    to surface an unauthorized server as a 401 before doing any work.
    """
    storage = TokenStorageFactory().get_storage(user_id, str(server.id))
    provider = await build_oauth_provider(server, storage, MCPServerRepository(db))
    await provider.initiate_authorization()


# --- Connection testing -----------------------------------------------------


async def test_connection(
    server: MCPServerDB, user_id: str, db: AsyncSession
) -> ConnectionTestResult:
    """End-to-end connectivity test for a *saved* server.

    Never raises for an expected auth condition: an unauthorized OAuth server is
    reported as ``oauth_required`` with the authorize URL so the caller can drive
    the popup flow, rather than a 401. Any other failure is captured in ``error``.
    """
    if server.auth_type == MCPAuthType.oauth2 and not await is_authorized(
        server, user_id
    ):
        try:
            await initiate_oauth(server, user_id, db)
        except OAuthAuthorizationRequired as e:
            return ConnectionTestResult(
                reachable=False, oauth_required=True, auth_url=e.url
            )
        except Exception as e:
            return ConnectionTestResult(reachable=False, error=str(e))

    try:
        async with connect_to_server(server, user_id, db) as client:
            tools = await list_all_mcp_tools(client)
            return ConnectionTestResult(
                reachable=True,
                tool_count=len(tools),
                tool_names=[tool.name for tool in tools],
            )
    except OAuthAuthorizationRequired as e:
        # e.g. a revoked-but-unexpired token: surface as re-authorization needed
        # so the caller can restart the OAuth flow rather than see a raw error.
        return ConnectionTestResult(
            reachable=False, oauth_required=True, auth_url=e.url
        )
    except Exception as e:
        return ConnectionTestResult(reachable=False, error=str(e))


async def probe_candidate(
    url: str, auth_type: MCPAuthType, *, api_key: str | None = None
) -> ConnectionTestResult:
    """Stateless reachability probe for candidate credentials (the create/edit
    form's "Test connection"), persisting nothing.

    Supports ``none`` and ``api_key``. OAuth is per-user and interactive, so it
    can't be validated before the server is saved — that's reported as an error
    telling the caller to save first.
    """
    if auth_type == MCPAuthType.oauth2:
        return ConnectionTestResult(
            reachable=False,
            error="OAuth servers must be saved first, then authenticated and tested.",
        )

    if auth_type == MCPAuthType.api_key and not api_key:
        # Without the key we'd do an anonymous handshake, which could report
        # success for a server that accepts unauthenticated requests — a config
        # that saving would then reject.
        return ConnectionTestResult(
            reachable=False,
            error="An API key is required to test this server.",
        )

    headers = (
        {"Authorization": f"Bearer {api_key}"}
        if auth_type == MCPAuthType.api_key and api_key
        else None
    )
    try:
        async with open_mcp_client(url, headers=headers) as client:
            tools = await list_all_mcp_tools(client)
            return ConnectionTestResult(
                reachable=True,
                tool_count=len(tools),
                tool_names=[tool.name for tool in tools],
            )
    except Exception as e:
        return ConnectionTestResult(reachable=False, error=str(e))
