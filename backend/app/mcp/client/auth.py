"""auxilia's OAuth client provider for MCP servers (MCP SDK v2 / httpx2).

``WebOAuthClientProvider`` adapts the SDK's ``OAuthClientProvider`` (an
``httpx2.Auth``) to a *serverless* web backend: there is no local callback
server to block on, so the authorization-code grant is split across two HTTP
requests —

1. :meth:`initiate_authorization` (or any authenticated MCP request hitting a
   401) runs the SDK's own discovery/registration flow; our
   :meth:`_perform_authorization_code_grant` override persists the PKCE state
   to Redis and raises :class:`OAuthAuthorizationRequired` with the authorize
   URL instead of waiting for a browser callback.
2. The ``/mcp-servers/oauth/callback`` endpoint — a separate request with a
   fresh provider — resolves the state from Redis and finishes the exchange
   via :meth:`manual_exchange`.

Compared to the v1 implementation this no longer hand-copies the SDK's 401
discovery sequence: the probe in :meth:`initiate_authorization` lets the
SDK's ``async_auth_flow`` drive it. Remaining per-server quirks are contained
in the overrides below.
"""

import logging
import secrets
from datetime import UTC, datetime
from urllib.parse import parse_qsl, urlencode, urljoin

import httpx2
from mcp.client.auth import OAuthClientProvider, OAuthFlowError, PKCEParameters
from mcp.client.auth.exceptions import OAuthRegistrationError
from mcp.client.auth.utils import (
    build_oauth_authorization_server_metadata_discovery_urls,
    create_oauth_metadata_request,
    handle_auth_metadata_response,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata
from pydantic import AnyHttpUrl, AnyUrl

from app.mcp.client.exceptions import OAuthAuthorizationRequired
from app.settings import app_settings


logger = logging.getLogger(__name__)


def _install_slash_tolerant_issuer_validation() -> None:
    """Make the SDK's SEP-2468 issuer check tolerate a trailing-slash-only
    difference.

    Real-world failure (BigQuery/Google): pydantic normalizes the PRM's
    ``authorization_servers`` entry to ``https://accounts.google.com/`` while
    Google's AS metadata declares ``issuer`` as ``https://accounts.google.com``
    — the SDK's byte-compare then rejects Google's own metadata. Upstream fix
    is open but unmerged (modelcontextprotocol/python-sdk#3013); drop this shim
    when it ships.
    """
    import mcp.client.auth.oauth2 as _sdk_oauth2
    from mcp.client.auth.utils import validate_metadata_issuer as _strict

    def tolerant(oauth_metadata, expected_issuer: str) -> None:
        if str(oauth_metadata.issuer).rstrip("/") == expected_issuer.rstrip("/"):
            return
        _strict(oauth_metadata, expected_issuer)

    _sdk_oauth2.validate_metadata_issuer = tolerant


_install_slash_tolerant_issuer_validation()


def strip_client_id_for_basic_auth(request: httpx2.Request) -> httpx2.Request:
    """Rebuild a token request without ``client_id`` in the form body when it
    also carries a Basic ``Authorization`` header.

    RFC 6749 §2.3 allows only one client-authentication method per request,
    but the SDK's token requests keep ``client_id`` in the body even when
    ``prepare_token_auth`` selected ``client_secret_basic``. Strict servers
    (e.g. Notion) reject the combination with "Client must not use multiple
    authentication methods". Stripping it keeps registrations stored as
    ``client_secret_basic`` working without re-registration.
    """
    if not request.headers.get("Authorization", "").startswith("Basic "):
        return request
    data = dict(parse_qsl(request.content.decode()))
    if "client_id" not in data:
        return request
    headers = {
        k: v for k, v in request.headers.items() if k.lower() != "content-length"
    }
    del data["client_id"]
    return httpx2.Request(request.method, request.url, data=data, headers=headers)


def build_oauth_client_metadata() -> OAuthClientMetadata:
    """Static OAuth client-registration metadata for auxilia.

    Scopes are intentionally omitted: they are discovered per-server from the
    Protected Resource Metadata (RFC 9728 ``scopes_supported``) during
    authorization, so there is nothing server-specific to configure here.

    ``token_endpoint_auth_method`` is requested explicitly: when omitted,
    RFC 7591 lets the server default to ``client_secret_basic``, whose token
    requests some strict servers (e.g. Notion) then reject (see
    ``strip_client_id_for_basic_auth``).

    ``application_type`` is ``web``: auxilia is a hosted client with a real
    HTTPS redirect URI, not a native app on a loopback redirect (the SDK's
    SEP-837 default).
    """
    return OAuthClientMetadata(
        client_name="auxilia",
        redirect_uris=[
            AnyUrl(f"{app_settings.backend_url}/mcp-servers/oauth/callback")
        ],
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        token_endpoint_auth_method="client_secret_post",
        application_type="web",
    )


class WebOAuthClientProvider(OAuthClientProvider):
    """Web OAuth client provider for MCP servers. Idea is to stick as close as possible to the official MCP SDK."""

    def __init__(
        self,
        *args,
        client_id: str | None = None,
        client_secret: str | None = None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self._client_id = client_id
        self._client_secret = client_secret

    async def _initialize(self):
        """Load stored state, then fill the gaps the SDK leaves.

        On top of the SDK's own ``_initialize`` (tokens + client info): restore
        the persisted AS metadata (the SDK never stores it, but the stateless
        callback/refresh requests need the token endpoint), inject static
        client credentials when the server was configured with them, and set
        the token expiry from the stored token (the SDK skips this on load, so
        a restarted process would treat any stored token as valid forever).
        """
        self.context.current_tokens = await self.context.storage.get_tokens()
        self.context.client_info = await self.context.storage.get_client_info()

        if not self.context.oauth_metadata:
            self.context.oauth_metadata = (
                await self.context.storage.get_oauth_metadata()
            )

        if (
            self.context.client_info
            and self.context.oauth_metadata
            and self.context.oauth_metadata.issuer
            == AnyHttpUrl("https://api.supabase.com/")
        ):
            logger.debug("Setting token endpoint auth method to client_secret_post")
            self.context.client_info.token_endpoint_auth_method = "client_secret_post"

        if (
            not self.context.client_info
            and self.context.client_metadata
            and self._client_id
        ):
            self.context.client_info = OAuthClientInformationFull(
                client_id=self._client_id,
                client_secret=self._client_secret,
                **self.context.client_metadata.model_dump(),
            )

        if self.context.current_tokens:
            self.context.update_token_expiry(self.context.current_tokens)

        self._initialized = True

    async def persist_client_info(self) -> None:
        """Persist static client registration to storage so the OAuth callback
        and the refresh path — separate requests with fresh providers — can
        recover client_id/secret. No-op when there are no static credentials
        (such servers register dynamically and persist during authorization)."""
        if not self._client_id:
            return
        await self.context.storage.set_client_info(
            OAuthClientInformationFull(
                client_id=self._client_id,
                client_secret=self._client_secret,
                **self.context.client_metadata.model_dump(),
            )
        )

    async def ensure_valid_token(self) -> bool:
        """Return True when a usable access token is available for this user.

        Refreshes an expired-but-refreshable token in place, reusing the SDK's
        own ``_refresh_token`` request builder and ``_handle_refresh_response``
        (which carries ``refresh_token``/``scope`` forward per RFC 6749 §6)
        rather than hand-rolling the token POST. Returns False when no token is
        stored, the token is expired with no refresh token, the stored client
        info/metadata is missing, or the refresh request fails.
        """
        if not self._initialized:
            await self._initialize()

        stored = await self.context.storage.get_stored_token()
        if not stored:
            return False

        is_expired = (
            stored.expires_at is not None and datetime.now(UTC) > stored.expires_at
        )
        if not is_expired:
            return True

        if not stored.token_payload.refresh_token:
            return False

        if not self.context.client_info:
            self.context.client_info = await self.context.storage.get_client_info()
        if not self.context.oauth_metadata:
            self.context.oauth_metadata = (
                await self.context.storage.get_oauth_metadata()
            )
        if not self.context.client_info or not self.context.oauth_metadata:
            return False

        try:
            request = await self._refresh_token()
            async with httpx2.AsyncClient() as client:
                response = await client.send(request)
                return await self._handle_refresh_response(response)
        except Exception:
            logger.warning(
                "OAuth refresh failed for %s", self.context.server_url, exc_info=True
            )
            return False

    async def _exchange_token_authorization_code(
        self, *args, **kwargs
    ) -> httpx2.Request:
        request = await super()._exchange_token_authorization_code(*args, **kwargs)
        return strip_client_id_for_basic_auth(request)

    async def _refresh_token(self) -> httpx2.Request:
        request = await super()._refresh_token()
        return strip_client_id_for_basic_auth(request)

    def _negotiate_registration_auth_method(self) -> None:
        """Align the requested ``token_endpoint_auth_method`` with what the
        authorization server advertises, before dynamic registration.

        We default to ``client_secret_post`` (see ``build_oauth_client_metadata``
        for why), but a server that only registers public clients — e.g. TikTok
        advertises ``token_endpoint_auth_methods_supported: ["none"]`` — rejects
        that default with ``invalid_client_metadata``. When our default isn't
        offered, prefer ``none`` (public client + PKCE, correct for a DCR client
        with no static secret), then ``client_secret_basic``. If the server
        advertises none of the methods this client can perform, raise rather than
        registering with a method we can't honour (which would only fail later at
        token exchange). Servers that don't advertise the field — or for which no
        AS metadata was discovered at all — keep our default.
        """
        metadata = self.context.oauth_metadata
        if metadata is None:
            return
        supported = metadata.token_endpoint_auth_methods_supported
        if not supported:
            return
        current = self.context.client_metadata.token_endpoint_auth_method
        if current in supported:
            return
        for preferred in ("none", "client_secret_post", "client_secret_basic"):
            if preferred in supported:
                self.context.client_metadata.token_endpoint_auth_method = preferred
                break
        else:
            raise OAuthFlowError(
                "MCP server supports no client-authentication method this client "
                f"can use (advertised: {supported})"
            )
        logger.debug(
            "Negotiated client auth method %s -> %s for %s",
            current,
            self.context.client_metadata.token_endpoint_auth_method,
            self.context.server_url,
        )

    async def initiate_authorization(self) -> None:
        """Start the OAuth flow explicitly, without opening an MCP session.

        Drives the SDK's own ``async_auth_flow`` — Protected Resource Metadata,
        Authorization Server Metadata, scope selection, dynamic registration —
        which ends in this class's ``_perform_authorization_code_grant``
        override raising :class:`OAuthAuthorizationRequired` with the authorize
        URL. Everything runs on a plain ``httpx2.AsyncClient`` (no MCP session,
        no anyio task group), so the exception propagates on the normal request
        stack instead of wrapped in an ``ExceptionGroup``.

        The flow's 401 branch is entered unconditionally (see
        :meth:`_drive_auth_flow`): it must not depend on the server actually
        challenging, because some servers (e.g. BigQuery) accept an
        unauthenticated ``initialize`` and only 401 business calls.

        A failed dynamic registration gets one retry after
        :meth:`_recover_registration_context` patches up what the SDK's inline
        flow can't (TikTok-style servers; see that method's docstring).
        """
        if not self._initialized:
            await self._initialize()

        for attempt in range(2):
            try:
                await self._drive_auth_flow()
            except (OAuthRegistrationError, OAuthFlowError):
                if attempt == 1 or not await self._recover_registration_context():
                    raise
                continue
            raise OAuthFlowError(
                "OAuth flow completed without an authorization redirect for "
                f"{self.context.server_url}"
            )

    async def _drive_auth_flow(self) -> None:
        """Pump the SDK's ``async_auth_flow`` generator by hand, feeding a
        synthetic 401 for the probe request so the discovery branch always runs.

        The httpx2 auth interface is a generator of requests: the SDK yields
        the original request, and on a 401 response yields its discovery /
        registration requests before performing authorization. Sending a real
        probe and waiting for a genuine 401 does not work universally — some
        servers (BigQuery) return 200 to unauthenticated ``initialize`` and
        challenge only business tool calls. So the probe request is never sent:
        it is answered with a synthetic 401 (no ``WWW-Authenticate``, which the
        SDK treats as "discover via well-known URLs"), while every request the
        flow yields after it — the actual discovery GETs and the DCR POST —
        goes over the wire. The flow terminates inside
        ``_perform_authorization_code_grant``, which raises
        :class:`OAuthAuthorizationRequired`.
        """
        probe = httpx2.Request("POST", str(self.context.server_url))
        flow = self.async_auth_flow(probe)
        async with httpx2.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            try:
                request = await flow.__anext__()
                while True:
                    if request is probe:
                        response = httpx2.Response(401, request=probe)
                    else:
                        response = await client.send(request)
                    request = await flow.asend(response)
            except StopAsyncIteration:
                return

    async def _recover_registration_context(self) -> bool:
        """Repair the discovery context after a failed dynamic registration,
        for servers the SDK's inline 401 flow can't discover or register with.

        Two known cases (both seen with TikTok):

        * The server publishes no RFC 9728 PRM and hosts its AS metadata under
          the MCP *path* (e.g. ``{path}/.well-known/openid-configuration``),
          which the SDK's root-only fallback misses. Seed
          ``context.oauth_metadata`` via path-aware discovery; the SDK's flow
          keeps a pre-seeded value when its own discovery finds nothing.
        * The server only registers public clients
          (``token_endpoint_auth_methods_supported: ["none"]``) and rejects our
          ``client_secret_post`` default. Negotiate the method against the
          (possibly just-seeded) AS metadata.

        Returns True when anything changed — i.e. a retry is worth it.
        """
        changed = False

        if self.context.oauth_metadata is None:
            urls = build_oauth_authorization_server_metadata_discovery_urls(
                str(self.context.server_url), self.context.server_url
            )
            async with httpx2.AsyncClient(
                timeout=10.0, follow_redirects=True
            ) as client:
                for url in urls:
                    response = await client.send(create_oauth_metadata_request(url))
                    ok, asm = await handle_auth_metadata_response(response)
                    if ok and asm:
                        self.context.oauth_metadata = asm
                        changed = True
                        break

        method_before = self.context.client_metadata.token_endpoint_auth_method
        self._negotiate_registration_auth_method()
        method_after = self.context.client_metadata.token_endpoint_auth_method

        return changed or method_after != method_before

    async def _perform_authorization_code_grant(self) -> tuple[str, str]:
        """Serverless override of the SDK's authorization-code grant.

        Instead of opening a browser (``redirect_handler``) and blocking on a
        local callback (``callback_handler``), persist the PKCE state to Redis
        — the ``/callback`` endpoint recovers it via ``manual_exchange`` — and
        raise :class:`OAuthAuthorizationRequired` carrying the authorize URL.
        """
        if self.context.oauth_metadata:
            await self.context.storage.set_oauth_metadata(self.context.oauth_metadata)

        if self.context.client_metadata.redirect_uris is None:
            raise OAuthFlowError("No redirect URIs provided")

        if (
            self.context.oauth_metadata
            and self.context.oauth_metadata.authorization_endpoint
        ):
            auth_endpoint = str(self.context.oauth_metadata.authorization_endpoint)
        else:
            auth_base_url = self.context.get_authorization_base_url(
                self.context.server_url
            )
            auth_endpoint = urljoin(auth_base_url, "/authorize")

        if not self.context.client_info:
            raise OAuthFlowError("No client info available")

        # The SDK's scope-selection step has run by now and overwritten
        # client_metadata.scope, so per-server scope fixes belong here.
        # TODO: Handle scopes automatically
        if str(self.context.server_url) == "https://gmailmcp.googleapis.com/mcp/v1":
            self.context.client_metadata.scope = (
                "openid "
                "https://www.googleapis.com/auth/userinfo.email "
                "https://www.googleapis.com/auth/gmail.readonly "
                "https://www.googleapis.com/auth/gmail.compose "
                "https://www.googleapis.com/auth/gmail.modify"
            )

        # Persist client_info so the OAuth callback (a separate HTTP request
        # with a fresh provider) and the refresh path can recover the
        # client_id/secret from storage.
        await self.context.storage.set_client_info(self.context.client_info)

        pkce_params = PKCEParameters.generate()
        state = secrets.token_urlsafe(32)

        await self.context.storage.set_verifier(state, pkce_params.code_verifier)

        auth_params = {
            "response_type": "code",
            "client_id": self.context.client_info.client_id,
            "redirect_uri": str(self.context.client_metadata.redirect_uris[0]),
            "state": state,
            "code_challenge": pkce_params.code_challenge,
            "code_challenge_method": "S256",
        }

        if (
            self.context.oauth_metadata
            and self.context.oauth_metadata.issuer
            == AnyHttpUrl("https://accounts.google.com/")
        ):
            auth_params["access_type"] = "offline"
            auth_params["prompt"] = "consent"

        if self.context.should_include_resource_param(self.context.protocol_version):
            auth_params["resource"] = self.context.get_resource_url()

        if self.context.client_metadata.scope:
            auth_params["scope"] = self.context.client_metadata.scope

        authorization_url = f"{auth_endpoint}?{urlencode(auth_params)}"

        raise OAuthAuthorizationRequired(authorization_url)

    async def manual_exchange(self, code: str, state: str):
        """Called by the /callback endpoint to finish the authorization-code
        exchange started by ``_perform_authorization_code_grant``."""
        if not self.context.client_info:
            self.context.client_info = await self.context.storage.get_client_info()

        if not self.context.client_info:
            raise OAuthFlowError("Client info not found in storage")

        if not self.context.oauth_metadata:
            self.context.oauth_metadata = (
                await self.context.storage.get_oauth_metadata()
            )

        verifier = await self.context.storage.get_verifier(state)

        if not verifier:
            raise OAuthFlowError("Session expired or invalid state")

        token_request = await self._exchange_token_authorization_code(
            auth_code=code, code_verifier=verifier
        )
        token_request.headers["Accept"] = "application/json"

        # The SDK's _handle_token_response accepts 200/201, validates scopes,
        # and persists the token to storage.
        async with httpx2.AsyncClient() as client:
            response = await client.send(token_request)
            await self._handle_token_response(response)

        await self.context.storage.delete_verifier(state)
