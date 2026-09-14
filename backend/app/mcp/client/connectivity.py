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

import asyncio
import logging
from collections.abc import AsyncIterator, Collection
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from uuid import UUID

from fastmcp.client import Client
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import DomainValidationError
from app.mcp.client.auth import (
    AUTH_METHOD_POST,
    WebOAuthClientProvider,
    build_oauth_client_metadata,
)
from app.mcp.client.connection import ConnectionSpec, open_client
from app.mcp.client.exceptions import OAuthAuthorizationRequired
from app.mcp.client.storage import RedisTokenStorage, TokenStorageFactory
from app.mcp.servers.models import (
    MCPAuthType,
    MCPServerDB,
    MCPServerOAuthCredentialsDB,
)
from app.mcp.servers.repository import MCPServerRepository
from app.mcp.servers.schemas import ConnectionTestResult
from app.redis_client import get_redis
from app.utils.encryption import decrypt_value


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
    row = (
        await repository.get_oauth_credentials(mcp_server.id)
        if repository is not None
        else None
    )
    return provider_with_credentials(mcp_server, storage, static_credentials(row))


@dataclass(frozen=True)
class StaticClientCredentials:
    """An admin-entered OAuth client registration, decrypted and ready to use.

    Servers without one register dynamically (DCR) during authorization.
    """

    client_id: str
    client_secret: str
    token_endpoint_auth_method: str


def static_credentials(
    row: MCPServerOAuthCredentialsDB | None,
) -> StaticClientCredentials | None:
    """Decrypt a credential row, once. `None` in, `None` out."""
    if row is None:
        return None
    return StaticClientCredentials(
        client_id=row.client_id,
        client_secret=decrypt_value(row.client_secret_encrypted),
        token_endpoint_auth_method=row.token_endpoint_auth_method or AUTH_METHOD_POST,
    )


def provider_with_credentials(
    mcp_server: MCPServerDB,
    storage: RedisTokenStorage,
    credentials: StaticClientCredentials | None,
) -> WebOAuthClientProvider:
    """The provider construction itself, once the credentials are in hand.

    Takes them already decrypted so a caller resolving the same server for
    several agents pays neither the query nor the decrypt per agent — the
    provider is what has to be fresh per call, not its inputs. Everyone else
    goes through :func:`build_oauth_provider`.
    """
    client_metadata = build_oauth_client_metadata()
    client_id = client_secret = None
    if credentials is not None:
        client_id = credentials.client_id
        client_secret = credentials.client_secret
        client_metadata.token_endpoint_auth_method = (
            credentials.token_endpoint_auth_method
        )
    return WebOAuthClientProvider(
        server_url=mcp_server.url,
        client_metadata=client_metadata,
        storage=storage,
        client_id=client_id,
        client_secret=client_secret,
    )


@dataclass
class CredentialCache:
    """A caller-owned memo of server credentials, keyed by server id.

    A run graph is a parent plus its direct subagents, which routinely bind the
    same MCP server; the credential behind it is the same for all of them and
    resolving it costs a query, a decrypt and (for a static OAuth registration)
    a Redis write each time. All three are done once per server here.

    One cache belongs to **one user and one graph** — `persisted` records writes
    to that user's token storage, so sharing a cache across users would skip a
    write that user still needs.

    Only the inputs are shared: :func:`resolve_connection` still builds a
    fresh ``WebOAuthClientProvider`` per call, because it is stateful and the
    graph's sessions are opened concurrently.
    """

    api_keys: dict[UUID, str | None] = field(default_factory=dict)
    oauth: dict[UUID, StaticClientCredentials | None] = field(default_factory=dict)
    persisted: set[UUID] = field(default_factory=set)


async def resolve_connection(
    server: MCPServerDB,
    user_id: str,
    repository: MCPServerRepository,
    *,
    credentials: CredentialCache | None = None,
) -> ConnectionSpec:
    """Auth type → how the transport authenticates. The single dispatch site.

    An API key becomes a Bearer header, OAuth2 the user's provider (an
    ``httpx2.Auth``), a ``none`` server neither. There used to be two copies of
    this and they had drifted (design review §4.1): one raised on an unknown
    auth type while the other fell through to connecting **unauthenticated**,
    and both formatted a missing API key straight into the header as the
    literal ``Bearer None``. Adding an auth scheme is one ``match`` arm.
    """
    match server.auth_type:
        case MCPAuthType.none:
            return ConnectionSpec(url=server.url)

        case MCPAuthType.api_key:
            api_keys = credentials.api_keys if credentials is not None else None
            if api_keys is not None and server.id in api_keys:
                key = api_keys[server.id]
            else:
                key = await repository.get_api_key(server.id)
                if api_keys is not None:
                    api_keys[server.id] = key
            if not key:
                # Used to send `Authorization: Bearer None`, which the server
                # answers with an opaque 401 — say what is actually wrong.
                raise DomainValidationError(
                    f"MCP server '{server.name}' is configured for API-key auth "
                    "but has no API key stored"
                )
            return ConnectionSpec(
                url=server.url, headers={"Authorization": f"Bearer {key}"}
            )

        case MCPAuthType.oauth2:
            storage = TokenStorageFactory().get_storage(user_id, str(server.id))
            memo = credentials.oauth if credentials is not None else None
            if memo is not None and server.id in memo:
                static = memo[server.id]
            else:
                static = static_credentials(
                    await repository.get_oauth_credentials(server.id)
                )
                if memo is not None:
                    memo[server.id] = static
            provider = provider_with_credentials(server, storage, static)
            # Static registrations must reach storage before anything uses the
            # provider: the callback and the refresh path run in later requests
            # with fresh providers and can only recover them from there. No-op
            # for a dynamically registered (DCR) server — and idempotent, so
            # one write per server per graph is enough (every agent would
            # otherwise write the same bytes again).
            if credentials is None or server.id not in credentials.persisted:
                await provider.persist_client_info()
                if credentials is not None:
                    credentials.persisted.add(server.id)
            return ConnectionSpec(url=server.url, auth=provider)

        case _:
            # Unreachable while the arms above cover `MCPAuthType`. Kept as a
            # raise rather than an assertion because the value comes from a DB
            # column: a row written by another schema version must fail loudly
            # instead of connecting unauthenticated.
            raise DomainValidationError(
                f"Unsupported MCP auth type: {server.auth_type!r}"
            )


# --- Session handshake ------------------------------------------------------


@asynccontextmanager
async def connect_to_server(
    mcp_server: MCPServerDB,
    user_id: str,
    db: AsyncSession,
    *,
    terminate_on_close: bool = True,
) -> AsyncIterator[Client]:
    """Connect to an MCP server for a specific user.

    Resolves the auth type through :func:`resolve_connection` — the user's
    OAuth provider, a Bearer ``Authorization`` header from the stored API key,
    or nothing at all — then opens the connection via ``open_client``. Callers
    list tools themselves (``await client.list_tools()``) when they need them;
    the MCP-app paths, which only read a resource or call one tool, no longer
    pay a ``tools/list`` per request.

    Args:
        mcp_server: MCP server configuration.
        user_id: The current user's ID.
        db: Database session (used to load credentials).
        terminate_on_close: When False, the session is NOT DELETEd on exit and is
            left to expire by the server's TTL. MCP App paths need this because
            Metabase binds artifacts (the embedded ``sessionToken``) to the MCP
            session — DELETEing it kills the token before the browser uses it.

    Yields:
        The connected FastMCP ``Client``.

    Raises:
        OAuthAuthorizationRequired: If OAuth authorization is needed.
    """
    spec = await resolve_connection(mcp_server, user_id, MCPServerRepository(db))
    async with open_client(spec, terminate_on_close=terminate_on_close) as client:
        yield client


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
    if not refresh:
        return await storage.get_tokens() is not None

    provider = await build_oauth_provider(server, storage)
    return await provider.ensure_valid_token()


# A probe of an *authorized* OAuth server is the expensive one: it decrypts the
# stored token and, when it has expired, does a token-refresh POST to the IdP.
# The frontend polls readiness in a loop, so without a cache every poll pays
# that — per server, per agent, forever.
#
# Only positives are cached. A negative is already cheap (no stored token, so
# the probe returns without any network work), and caching it would leave a
# user who has just completed the OAuth popup staring at "not connected" for the
# length of the TTL. The cost of that choice is the other direction: a token
# revoked at the IdP keeps reading as authorized for up to the TTL. Thirty
# seconds of lag before the run fails in-thread is the cheaper mistake.
_PROBE_CACHE_TTL_SECONDS = 30
# The fail-open handlers below only catch *raised* errors. A Redis that accepts
# the connection and then stalls would hang the polled readiness endpoint and
# the run-start preflight indefinitely, so every cache round trip gets a
# deadline. The cache is an optimization; missing it costs a probe.
_CACHE_TIMEOUT_SECONDS = 2.0


def _probe_cache_key(user_id: str, server_id: UUID) -> str:
    """Deliberately shaped `mcp:{user}:{server}:...`, matching `RedisTokenStorage`.

    That layout is what `TokenStorageFactory.clear_server_data` /
    `clear_user_server_data` scan (`mcp:*:{server_id}:*`). A key outside it
    survives every purge, so a user who revoked their connection — or a server
    whose URL or auth type just changed — would keep reading as authorized until
    this TTL lapsed, from a cache nothing knows how to invalidate.
    """
    return f"mcp:{user_id}:{server_id}:authprobe"


async def probe_authorization(
    servers: Collection[MCPServerDB], user_id: str
) -> dict[UUID, bool]:
    """Whether the user is authorized for each server — concurrent, fail-open,
    and memoized per (user, server).

    The single implementation behind both the polled readiness endpoint and the
    run-start preflight, which used to carry divergent copies: one sequential
    and fail-loud (so a single probe raising 500'd the polled endpoint), one
    concurrent and fail-open (design review §4.1).

    **Fail-open**: a probe that raises counts as authorized. Readiness is a
    convenience, not a security boundary — the server itself rejects an
    unauthorized call — so an IdP outage must not make every agent unlaunchable.

    Probes are independent per (user, server), so they run concurrently: the
    check costs one round trip, not one per server.
    """
    if not servers:
        return {}

    redis = get_redis()
    unique = {server.id: server for server in servers}

    try:
        async with asyncio.timeout(_CACHE_TIMEOUT_SECONDS):
            cached = await redis.mget(
                [_probe_cache_key(user_id, sid) for sid in unique]
            )
    except Exception:  # noqa: BLE001 — a cache outage degrades to probing, never to failing
        logger.warning("Authorization probe cache read failed", exc_info=True)
        cached = [None] * len(unique)

    results: dict[UUID, bool] = {}
    to_probe: list[MCPServerDB] = []
    for (server_id, server), hit in zip(unique.items(), cached, strict=True):
        if hit == "1":
            results[server_id] = True
        else:
            to_probe.append(server)

    async def _probe(server: MCPServerDB) -> bool:
        try:
            return await is_authorized(server, user_id)
        except Exception:  # noqa: BLE001 — fail-open, see the docstring
            logger.warning(
                "Authorization probe for MCP server %s failed; treating as authorized",
                server.id,
                exc_info=True,
            )
            return True

    probed = await asyncio.gather(*(_probe(server) for server in to_probe))
    authorized_ids: list[UUID] = []
    for server, ok in zip(to_probe, probed, strict=True):
        results[server.id] = ok
        if ok:
            authorized_ids.append(server.id)

    if authorized_ids:
        try:
            async with asyncio.timeout(_CACHE_TIMEOUT_SECONDS):
                async with redis.pipeline(transaction=False) as pipe:
                    for server_id in authorized_ids:
                        pipe.set(
                            _probe_cache_key(user_id, server_id),
                            "1",
                            ex=_PROBE_CACHE_TTL_SECONDS,
                        )
                    await pipe.execute()
        except Exception:  # noqa: BLE001 — a cache outage degrades to probing, never to failing
            logger.warning("Authorization probe cache write failed", exc_info=True)

    return results


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
        except Exception as e:  # noqa: BLE001 — any failure is reported as unreachable
            return ConnectionTestResult(reachable=False, error=str(e))

    try:
        async with connect_to_server(server, user_id, db) as client:
            tools = await client.list_tools()
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
    except Exception as e:  # noqa: BLE001 — any failure is reported as unreachable
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
        async with open_client(ConnectionSpec(url=url, headers=headers)) as client:
            tools = await client.list_tools()
            return ConnectionTestResult(
                reachable=True,
                tool_count=len(tools),
                tool_names=[tool.name for tool in tools],
            )
    except Exception as e:  # noqa: BLE001 — any failure is reported as unreachable
        return ConnectionTestResult(reachable=False, error=str(e))
