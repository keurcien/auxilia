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

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import DomainError
from app.mcp.client.auth import WebOAuthClientProvider, build_oauth_client_metadata
from app.mcp.client.exceptions import OAuthAuthorizationRequired
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


# --- Session handshake ------------------------------------------------------

# Safety bound for tools/list pagination. A well-behaved server eventually returns
# a falsy nextCursor; this caps a misbehaving one that emits endless new cursors.
MAX_TOOL_LIST_PAGES = 1000


async def _list_all_tools(session: ClientSession) -> list:
    """Page through ``tools/list``, guarding against a server that never ends
    pagination. A repeated or cyclic ``nextCursor`` is detected and a runaway page
    count is capped — otherwise the loop would spin forever, accumulating tools.
    """
    tools = []
    cursor: str | None = None
    seen_cursors: set[str] = set()
    for _ in range(MAX_TOOL_LIST_PAGES):
        response = await session.list_tools(cursor=cursor)
        tools.extend(response.tools)
        cursor = response.nextCursor
        if not cursor:
            return tools
        if cursor in seen_cursors:
            raise DomainError(
                "MCP server returned a repeated tools/list cursor; "
                "aborting to avoid an infinite pagination loop."
            )
        seen_cursors.add(cursor)
    raise DomainError(
        f"MCP server exceeded {MAX_TOOL_LIST_PAGES} tools/list pages; "
        "aborting to avoid an unbounded pagination loop."
    )


@asynccontextmanager
async def _open_session(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    auth=None,
    terminate_on_close: bool = True,
):
    """Open a Streamable HTTP MCP session, initialize it, and list its tools.

    The low-level primitive shared by every handshake path: the DB-backed
    :func:`connect_to_server` and the stateless :func:`probe_candidate`. Errors
    raised while listing tools (or from the ``async with`` body) are wrapped in
    ``DomainError`` to give callers a clean message.
    """
    client_args: dict = {"url": url}
    if headers:
        client_args["headers"] = headers
    if auth is not None:
        client_args["auth"] = auth

    async with streamablehttp_client(
        **client_args, terminate_on_close=terminate_on_close
    ) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            try:
                tools = await _list_all_tools(session)
                yield session, tools
            except Exception as e:
                raise DomainError(str(e)) from e


@asynccontextmanager
async def connect_to_server(
    mcp_server: MCPServerDB,
    user_id: str,
    db: AsyncSession,
    *,
    terminate_on_close: bool = True,
):
    """Connect to an MCP server for a specific user and initialize the session.

    Resolves the auth type to the right transport arguments — the user's OAuth
    provider, a Bearer ``Authorization`` header from the stored API key, or a
    plain URL — then opens the session via :func:`_open_session`.

    Args:
        mcp_server: MCP server configuration.
        user_id: The current user's ID.
        db: Database session (used to load credentials).
        terminate_on_close: When False, the session is NOT DELETEd on exit and is
            left to expire by the server's TTL. MCP App paths need this because
            Metabase binds artifacts (the embedded ``sessionToken``) to the MCP
            session — DELETEing it kills the token before the browser uses it.

    Yields:
        tuple: (session, tools) - Initialized session and available tools.

    Raises:
        OAuthAuthorizationRequired: If OAuth authorization is needed.
    """
    repository = MCPServerRepository(db)
    storage = TokenStorageFactory().get_storage(user_id, str(mcp_server.id))

    if mcp_server.auth_type == MCPAuthType.oauth2:
        provider = await build_oauth_provider(mcp_server, storage, repository)
        await provider.persist_client_info()
        async with _open_session(
            mcp_server.url, auth=provider, terminate_on_close=terminate_on_close
        ) as result:
            yield result
    elif mcp_server.auth_type == MCPAuthType.api_key:
        api_key = await repository.get_api_key(mcp_server.id)
        async with _open_session(
            mcp_server.url,
            headers={"Authorization": f"Bearer {api_key}"},
            terminate_on_close=terminate_on_close,
        ) as result:
            yield result
    else:
        async with _open_session(
            mcp_server.url, terminate_on_close=terminate_on_close
        ) as result:
            yield result


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
        async with connect_to_server(server, user_id, db) as (_, tools):
            return ConnectionTestResult(
                reachable=True,
                tool_count=len(tools),
                tool_names=[tool.name for tool in tools],
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

    headers = (
        {"Authorization": f"Bearer {api_key}"}
        if auth_type == MCPAuthType.api_key and api_key
        else None
    )
    try:
        async with _open_session(url, headers=headers) as (_, tools):
            return ConnectionTestResult(
                reachable=True,
                tool_count=len(tools),
                tool_names=[tool.name for tool in tools],
            )
    except Exception as e:
        return ConnectionTestResult(reachable=False, error=str(e))
