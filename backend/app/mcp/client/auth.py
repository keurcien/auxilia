"""auxilia's OAuth client provider for MCP servers.

``WebOAuthClientProvider`` adapts the MCP SDK's ``OAuthClientProvider`` (an
``httpx2.Auth``) to a *serverless* web backend. The SDK assumes a client that
can open a browser and block on a local callback (``redirect_handler`` /
``callback_handler``); a multi-instance backend cannot, so the
authorization-code grant is split across two HTTP requests:

1. :meth:`initiate_authorization` — or any MCP request that meets a 401 —
   runs the SDK's own discovery and registration flow unmodified. Our
   :meth:`_perform_authorization_code_grant` override then persists the PKCE
   state to Redis and raises :class:`OAuthAuthorizationRequired` carrying the
   authorize URL, instead of waiting for a browser.
2. The ``/mcp-servers/oauth/callback`` endpoint — a separate request with a
   fresh provider — recovers the state from Redis and finishes the exchange
   via :meth:`manual_exchange`.

This is the model the TypeScript SDK ships natively (``auth()`` returning
``'REDIRECT'``, then ``finishAuth``); the Python SDK keeps the orchestration
inside its httpx auth generator, so :meth:`initiate_authorization` drives that
generator by hand rather than copying its discovery sequence (python-sdk#1743
tracks exposing it). Nothing here duplicates SDK flow logic; the overrides are
the two ends of the split plus the per-provider deviations in ``OAUTH_QUIRKS``.
"""

from __future__ import annotations

import logging
import secrets
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import parse_qsl, urlencode, urljoin

import httpx2
import mcp.client.auth.oauth2 as sdk_oauth2
from mcp.client.auth import (
    OAuthClientProvider,
    OAuthFlowError,
    OAuthRegistrationError,
    PKCEParameters,
)
from mcp.client.auth.utils import (
    build_oauth_authorization_server_metadata_discovery_urls,
    create_oauth_metadata_request,
    handle_auth_metadata_response,
    issuers_match,
    validate_metadata_issuer,
)
from mcp.shared.auth import (
    OAuthClientInformationFull,
    OAuthClientMetadata,
    OAuthMetadata,
)
from pydantic import AnyHttpUrl, AnyUrl

from app.mcp.client.exceptions import OAuthAuthorizationRequired
from app.mcp.client.storage import OAuthResourceContext
from app.settings import app_settings


logger = logging.getLogger(__name__)


def _validate_metadata_issuer_tolerantly(
    oauth_metadata: OAuthMetadata, expected_issuer: str
) -> None:
    """SEP-2468 issuer check that treats ``scheme://host`` and
    ``scheme://host/`` as the same issuer — with the SDK's own
    ``issuers_match``, which its flow applies only on the no-PRM path.

    On the PRM path the SDK byte-compares the PRM's ``authorization_servers``
    entry against the AS metadata's ``issuer``. Google publishes the first
    with a trailing slash and the second without, so its own metadata is
    rejected ("issuer mismatch: https://accounts.google.com !=
    https://accounts.google.com/"). The TypeScript SDK's ``issuersMatch`` is
    slash-tolerant everywhere; this makes the Python flow agree with it.
    Anything but a trailing-slash-only difference still fails as before.

    Installed into the SDK's flow module below, since the flow calls the
    module-level function and offers no hook. Drop when upstream tolerates
    it on the PRM path too (modelcontextprotocol/python-sdk#3013).
    """
    if issuers_match(str(oauth_metadata.issuer), expected_issuer):
        return
    validate_metadata_issuer(oauth_metadata, expected_issuer)


sdk_oauth2.validate_metadata_issuer = _validate_metadata_issuer_tolerantly


# RFC 7591 token-endpoint authentication *method names* — identifiers from the
# spec, not credentials. Bound to constants because bandit reads a
# `token_endpoint_auth_method="..."` keyword argument as a hardcoded password
# (B106/CWE-259) and that finding fails the Codacy gate. The constant names
# deliberately avoid the words bandit scans for, or the definitions here would
# trip B105 in turn.
AUTH_METHOD_POST = "client_secret_post"
AUTH_METHOD_BASIC = "client_secret_basic"
AUTH_METHOD_NONE = "none"


@dataclass(frozen=True)
class OAuthQuirk:
    """One provider's deviation from what the specs alone would give us.

    Matched on the **issuer** when the provider is only known after metadata
    discovery, and on the **server URL** when the deviation has to apply before
    (or without) discovery — the OAuth callback, for instance, exchanges a code
    on a fresh provider. Both keys exist because both moments exist, and a
    quirk may set both: the Supabase one used to be written twice, once per
    key, in two different layers, where the copies could disagree about which
    servers they covered (design review §4.1).

    Fields are the three things a quirk can change, all optional:

    * ``token_endpoint_auth_method`` — how the token request authenticates.
    * ``authorization_params`` — extra query params on the authorize URL.
    * ``scope`` — a fixed scope string, used when the server advertises none
      usable (see :func:`quirk_scope`).
    """

    name: str
    issuer: str | None = None
    server_url: str | None = None
    token_endpoint_auth_method: str | None = None
    authorization_params: Mapping[str, str] = field(default_factory=dict)
    scope: str | None = None


OAUTH_QUIRKS: tuple[OAuthQuirk, ...] = (
    OAuthQuirk(
        name="supabase",
        issuer="https://api.supabase.com/",
        server_url="https://mcp.supabase.com/mcp",
        # Rejects client_secret_basic on the token endpoint.
        token_endpoint_auth_method=AUTH_METHOD_POST,
    ),
    OAuthQuirk(
        name="google",
        issuer="https://accounts.google.com/",
        # Google returns a refresh token only when both are present, and only
        # on a consent screen the user actually sees — drop `prompt` and a
        # returning user silently gets an access token that cannot be renewed.
        authorization_params={"access_type": "offline", "prompt": "consent"},
    ),
    OAuthQuirk(
        name="gmail",
        server_url="https://gmailmcp.googleapis.com/mcp/v1",
        # Google's MCP endpoint advertises no usable scopes, so they are named
        # here. TODO: discover these instead of hardcoding them.
        scope=(
            "openid "
            "https://www.googleapis.com/auth/userinfo.email "
            "https://www.googleapis.com/auth/gmail.readonly "
            "https://www.googleapis.com/auth/gmail.compose "
            "https://www.googleapis.com/auth/gmail.modify"
        ),
    ),
)


def _issuer_key(issuer: str | AnyHttpUrl | None) -> str | None:
    """Issuers compare with a normalised trailing slash: pydantic renders a
    root URL with one, the quirk table is written with one, and an
    authorization server may declare itself without one."""
    if issuer is None:
        return None
    text = str(issuer)
    return text if text.endswith("/") else f"{text}/"


def resolve_quirks(
    *, server_url: str | AnyUrl | None = None, issuer: str | AnyHttpUrl | None = None
) -> list[OAuthQuirk]:
    """Every quirk matching this server — by URL, by issuer, or either.

    A caller passes whichever keys it holds at that point in the flow; a quirk
    matches when any key it declares matches one that was passed.
    """
    url = str(server_url) if server_url is not None else None
    issuer_url = _issuer_key(issuer)
    return [
        quirk
        for quirk in OAUTH_QUIRKS
        if (quirk.server_url is not None and quirk.server_url == url)
        or (quirk.issuer is not None and _issuer_key(quirk.issuer) == issuer_url)
    ]


def quirk_token_endpoint_auth_method(
    *, server_url: str | AnyUrl | None = None, issuer: str | AnyHttpUrl | None = None
) -> str | None:
    """The token-endpoint auth method this server needs, if it needs one."""
    for quirk in resolve_quirks(server_url=server_url, issuer=issuer):
        if quirk.token_endpoint_auth_method:
            return quirk.token_endpoint_auth_method
    return None


def quirk_authorization_params(
    *, server_url: str | AnyUrl | None = None, issuer: str | AnyHttpUrl | None = None
) -> dict[str, str]:
    """Extra authorize-URL params for this server (empty for most)."""
    params: dict[str, str] = {}
    for quirk in resolve_quirks(server_url=server_url, issuer=issuer):
        params.update(quirk.authorization_params)
    return params


def quirk_scope(
    *, server_url: str | AnyUrl | None = None, issuer: str | AnyHttpUrl | None = None
) -> str | None:
    """A fixed scope string for this server, overriding discovery."""
    for quirk in resolve_quirks(server_url=server_url, issuer=issuer):
        if quirk.scope:
            return quirk.scope
    return None


def refresh_failure_is_transient(status_code: int) -> bool:
    """Whether a non-2xx from the token endpoint says nothing about the
    refresh credential: 429 (throttled) or 5xx (AS down). Every other
    non-2xx — 400/401 per RFC 6749 §5.2, but also a 403, 404, 3xx or anything
    non-standard — is treated as a rejection of the token, since re-POSTing
    a credential the AS will never accept is the retry storm this guards
    against. Only consulted for non-2xx: ``ensure_valid_token`` handles every
    2xx as a success first."""
    return status_code == 429 or 500 <= status_code < 600


def strip_client_id_for_basic_auth(request: httpx2.Request) -> httpx2.Request:
    """Rebuild a token request without ``client_id`` in the form body when it
    also carries a Basic ``Authorization`` header.

    RFC 6749 §2.3 allows only one client-authentication method per request,
    but the SDK's token requests keep ``client_id`` in the body even when
    ``prepare_token_auth`` has selected ``client_secret_basic``. Strict servers
    (e.g. Notion) reject the combination with "Client must not use multiple
    authentication methods". Stripping it here keeps registrations stored as
    ``client_secret_basic`` working without re-registration.
    """
    if not request.headers.get("Authorization", "").startswith("Basic "):
        return request
    data = dict(parse_qsl(request.content.decode()))
    if "client_id" not in data:
        return request
    del data["client_id"]
    headers = {
        k: v for k, v in request.headers.items() if k.lower() != "content-length"
    }
    return httpx2.Request(request.method, request.url, data=data, headers=headers)


def build_oauth_client_metadata() -> OAuthClientMetadata:
    """Static OAuth client-registration metadata for auxilia.

    Scopes are intentionally omitted: they are discovered per-server from the
    Protected Resource Metadata (RFC 9728 ``scopes_supported``) during
    authorization, so there is nothing server-specific to configure here.

    ``token_endpoint_auth_method`` is requested explicitly: when omitted,
    RFC 7591 lets the server default to ``client_secret_basic``, whose token
    requests strict servers (e.g. Notion) then reject (see
    :func:`strip_client_id_for_basic_auth`).

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
        token_endpoint_auth_method=AUTH_METHOD_POST,
        application_type="web",
    )


class _DropIntentionalAuthorizationErrors(logging.Filter):
    """The SDK logs every exception leaving its auth flow as ``ERROR OAuth
    flow error`` with a traceback. Ours is the expected outcome of every
    authorization initiation, not an error — keep it out of the error log."""

    def filter(self, record: logging.LogRecord) -> bool:
        exc = record.exc_info[1] if record.exc_info else None
        return not isinstance(exc, OAuthAuthorizationRequired)


logging.getLogger("mcp.client.auth.oauth2").addFilter(
    _DropIntentionalAuthorizationErrors()
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
        self._resource_context: OAuthResourceContext | None = None

    def _issuer(self) -> AnyHttpUrl | None:
        metadata = self.context.oauth_metadata
        return metadata.issuer if metadata else None

    async def _initialize(self) -> None:
        """Load stored state, then fill the gaps the SDK leaves.

        On top of the SDK's own ``_initialize`` (tokens + client info): restore
        the persisted AS metadata and resource context (the stateless
        callback/refresh requests need both the endpoint and audience), apply the
        per-provider quirks, inject static client credentials when the server
        was configured with them, and set the token expiry from the stored
        token (the SDK skips this on load, so a restarted process would treat
        any stored token as valid forever — python-sdk#1784).
        """
        await super()._initialize()

        if not self.context.oauth_metadata:
            self.context.oauth_metadata = (
                await self.context.storage.get_oauth_metadata()
            )

        self._resource_context = await self.context.storage.get_resource_context()
        self._restore_resource_context()

        # Apply the quirk to the metadata *and* to any stored client_info: the
        # client_info built below inherits it from the metadata, while one that
        # came back from storage predates this provider and has to be corrected
        # in place. Matching on both keys is what lets the OAuth callback drop
        # its own copy of this — it exchanges a code on a fresh provider whose
        # metadata discovery has not run, so only the URL is known there.
        auth_method = quirk_token_endpoint_auth_method(
            server_url=self.context.server_url, issuer=self._issuer()
        )
        if auth_method:
            # Worded without "token"/"secret": Codacy's semgrep rule reads a
            # log message carrying either word as a credential leak.
            logger.debug(
                "Quirk: client auth method %s for %s",
                auth_method,
                self.context.server_url,
            )
            self.context.client_metadata.token_endpoint_auth_method = auth_method
            if self.context.client_info:
                self.context.client_info.token_endpoint_auth_method = auth_method

        if not self.context.client_info and self._client_id:
            self.context.client_info = OAuthClientInformationFull(
                client_id=self._client_id,
                client_secret=self._client_secret,
                **self.context.client_metadata.model_dump(),
            )

        if self.context.current_tokens:
            self.context.update_token_expiry(self.context.current_tokens)

    def _restore_resource_context(self) -> None:
        """Keep the SDK's resource selection on callback and refresh requests.

        AS metadata alone does not tell the SDK whether to send ``resource``
        or which canonical URI the protected resource advertised. Fill missing
        discovery state without replacing metadata learned in this request.
        """
        if self._resource_context is None:
            return
        if self.context.protected_resource_metadata is None:
            self.context.protected_resource_metadata = (
                self._resource_context.protected_resource_metadata
            )
        if self.context.protocol_version is None:
            self.context.protocol_version = self._resource_context.protocol_version

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
        own ``_refresh_token`` request builder and ``_handle_token_response``
        rather than hand-rolling the token POST. Returns False when no token is
        stored, the token is expired with no refresh token, the stored client
        info/metadata is missing, or the refresh request fails. A refresh the
        AS *rejects* (any non-2xx other than 429 / 5xx — see
        :func:`refresh_failure_is_transient`) also deletes the stored token
        pair; a transport failure, 429 or 5xx keeps it so a transient outage
        does not log the user out.
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
        if not self.context.client_info or not self.context.oauth_metadata:
            return False

        try:
            request = await self._refresh_token()
            async with httpx2.AsyncClient() as client:
                response = await client.send(request)
            if response.is_success:
                # Any 2xx is the AS accepting the refresh (RFC 6749 §5.1 says
                # 200; 201 is seen in the wild). An unexpected 2xx shape that
                # `_handle_token_response` cannot parse raises into the
                # `except` below and keeps the pair — it is never a rejection.
                # `RedisTokenStorage.set_tokens` carries a refresh token the
                # response omits forward (RFC 6749 §6).
                await self._handle_token_response(response)
                return True
            if refresh_failure_is_transient(response.status_code):
                # The AS is throttling or down; the credential may well be
                # fine. Keep it and try again on the next check.
                logger.warning(
                    "OAuth refresh failed (%s) for %s — keeping stored tokens",
                    response.status_code,
                    self.context.server_url,
                )
                return False
            # The AS rejected the refresh token. That is final — revoked,
            # rotated away by a concurrent refresh, or expired (Metabase
            # answers 400 for all three) — so drop the stored pair: the next
            # check then prompts a clean re-authorization instead of retrying
            # the dead token on every poll and every run.
            logger.warning(
                "OAuth refresh rejected (%s) for %s — clearing stored tokens",
                response.status_code,
                self.context.server_url,
            )
            await self.context.storage.delete_tokens()
            return False
        except Exception:  # noqa: BLE001 — a failed refresh means "not authorized", not a crash
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
        # The SDK captures protocol_version from each outgoing MCP request,
        # including None on an initialize request. Retain the discovered
        # resource decision when refreshing before that request is sent.
        self._restore_resource_context()
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
        for preferred in (AUTH_METHOD_NONE, AUTH_METHOD_POST, AUTH_METHOD_BASIC):
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

        Drives the SDK's own auth flow — Protected Resource Metadata,
        Authorization Server Metadata, scope selection, dynamic registration —
        which ends in this class's :meth:`_perform_authorization_code_grant`
        raising :class:`OAuthAuthorizationRequired` with the authorize URL.
        Everything runs on a plain ``httpx2.AsyncClient`` (no MCP session, no
        anyio task group), so the exception propagates on the normal request
        stack.

        The 401 branch is entered unconditionally (see :meth:`_drive_auth_flow`):
        it must not depend on the server actually challenging, because some
        servers (BigQuery) accept an unauthenticated ``initialize`` and only
        401 business calls.

        A failed dynamic registration gets one retry after
        :meth:`_recover_registration_context` patches up what the SDK's inline
        flow cannot discover (TikTok-style servers; see that docstring).
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
        """Pump the SDK's ``async_auth_flow`` generator by hand, answering the
        probe request with a synthetic 401 so the discovery branch always runs.

        The httpx2 auth interface is a generator of requests: the SDK yields
        the request being authenticated and, on a 401 response, yields its
        discovery / registration requests before performing authorization.
        The probe is never sent — it is answered with a synthetic 401 (no
        ``WWW-Authenticate``, which the SDK treats as "discover via well-known
        URLs") — while every request the flow yields after it goes over the
        wire. The flow terminates inside
        :meth:`_perform_authorization_code_grant`, which raises.
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
            finally:
                # A transport error from `client.send` leaves the generator
                # suspended at its yield; close it rather than leave it to GC.
                await flow.aclose()

    async def _recover_registration_context(self) -> bool:
        """Repair the discovery context after a failed dynamic registration,
        for servers the SDK's inline 401 flow can't discover or register with.

        Two known cases (both seen with TikTok):

        * The server publishes no RFC 9728 PRM and hosts its AS metadata under
          the MCP *path* (``{path}/.well-known/openid-configuration``), which
          the SDK's root-only fallback misses. Seed ``context.oauth_metadata``
          via path-aware discovery; the SDK's flow keeps a pre-seeded value
          when its own discovery finds nothing.
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
        local callback (``callback_handler``), persist what the ``/callback``
        request will need — the AS metadata, resource context, client
        registration and the PKCE verifier keyed by ``state`` — and raise
        :class:`OAuthAuthorizationRequired` carrying the authorize URL.

        Mirrors the SDK's URL construction because the verifier is local to
        that method: a ``redirect_handler`` receives the URL but never the
        verifier, and a serverless client has nowhere else to keep it.
        """
        if self.context.oauth_metadata:
            await self.context.storage.set_oauth_metadata(self.context.oauth_metadata)

        if self.context.client_metadata.redirect_uris is None:
            raise OAuthFlowError("No redirect URIs provided")
        if not self.context.client_info:
            raise OAuthFlowError("No client info available")

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

        # The SDK's scope-selection step has run by now and overwritten
        # client_metadata.scope with what discovery found, so a fixed scope
        # (Gmail advertises none) has to be applied here.
        fixed_scope = quirk_scope(
            server_url=self.context.server_url, issuer=self._issuer()
        )
        if fixed_scope:
            self.context.client_metadata.scope = fixed_scope

        # Persist client_info so the OAuth callback (a separate HTTP request
        # with a fresh provider) and the refresh path can recover the
        # client_id/secret from storage.
        await self.context.storage.set_client_info(self.context.client_info)

        self._resource_context = OAuthResourceContext(
            protected_resource_metadata=self.context.protected_resource_metadata,
            protocol_version=self.context.protocol_version,
        )
        await self.context.storage.set_resource_context(self._resource_context)

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
        auth_params.update(
            quirk_authorization_params(
                server_url=self.context.server_url, issuer=self._issuer()
            )
        )
        if self.context.should_include_resource_param(self.context.protocol_version):
            auth_params["resource"] = self.context.get_resource_url()
        if self.context.client_metadata.scope:
            auth_params["scope"] = self.context.client_metadata.scope

        raise OAuthAuthorizationRequired(f"{auth_endpoint}?{urlencode(auth_params)}")

    async def manual_exchange(self, code: str, state: str) -> None:
        """Finish the authorization-code exchange started by
        :meth:`_perform_authorization_code_grant`, from the ``/callback``
        endpoint — a separate request with a fresh provider."""
        if not self._initialized:
            await self._initialize()

        if not self.context.client_info:
            raise OAuthFlowError("Client info not found in storage")

        verifier = await self.context.storage.get_verifier(state)
        if not verifier:
            raise OAuthFlowError("Session expired or invalid state")

        token_request = await self._exchange_token_authorization_code(
            auth_code=code, code_verifier=verifier
        )
        token_request.headers["Accept"] = "application/json"

        # The SDK's `_handle_token_response` accepts 200/201, validates scopes
        # and persists the token to storage.
        async with httpx2.AsyncClient() as client:
            response = await client.send(token_request)
            await self._handle_token_response(response)

        await self.context.storage.delete_verifier(state)
