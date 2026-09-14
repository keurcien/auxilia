"""Tests for WebOAuthClientProvider (MCP SDK v2 / httpx2).

`initiate_authorization` drives the SDK's own auth flow — the probe request is
answered with a synthetic 401 and never sent — so discovery (RFC 9728 PRM +
RFC 8414/OIDC AS metadata), scope selection and dynamic registration are the
SDK's; our `_perform_authorization_code_grant` override then raises
OAuthAuthorizationRequired with the authorize URL, on the plain request stack
(no MCP session / task group). These tests run the real SDK flow against an
httpx2 MockTransport serving the discovery endpoints.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import httpx2
import pytest
from mcp.client.auth import OAuthFlowError
from mcp.shared.auth import (
    OAuthClientInformationFull,
    OAuthMetadata,
    OAuthToken,
)

from app.mcp.client.auth import WebOAuthClientProvider, build_oauth_client_metadata
from app.mcp.client.exceptions import OAuthAuthorizationRequired
from app.mcp.client.storage import StoredToken


BIGQUERY_URL = "https://bigquery.googleapis.com/mcp"
GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_ISSUER = "https://accounts.google.com/"


class _FakeStorage:
    """Minimal TokenStorage: unauthenticated, records what gets persisted."""

    def __init__(self):
        self.client_info = None
        self.oauth_metadata = None
        self.verifier = None

    async def get_tokens(self):
        return None

    async def set_tokens(self, tokens):
        self.tokens = tokens

    async def get_client_info(self):
        return self.client_info

    async def set_client_info(self, client_info):
        self.client_info = client_info

    async def get_oauth_metadata(self):
        return self.oauth_metadata

    async def set_oauth_metadata(self, metadata):
        self.oauth_metadata = metadata

    async def set_verifier(self, state, verifier):
        self.verifier = (state, verifier)


def _make_provider() -> WebOAuthClientProvider:
    return WebOAuthClientProvider(
        server_url=BIGQUERY_URL,
        client_metadata=build_oauth_client_metadata(),
        storage=_FakeStorage(),
        client_id="client-123",
        client_secret="secret-xyz",
    )


def _serve(monkeypatch, routes):
    """Route every httpx2.AsyncClient request through a MockTransport.

    `routes` maps "METHOD https://host/path" (no query) to a dict (returned as
    JSON 200), an httpx2.Response, or a callable taking the request.
    """

    def handler(request: httpx2.Request) -> httpx2.Response:
        key = f"{request.method} {str(request.url).split('?')[0]}"
        result = routes.get(key)
        if result is None:
            return httpx2.Response(404)
        if callable(result):
            result = result(request)
        if isinstance(result, httpx2.Response):
            return result
        return httpx2.Response(200, json=result)

    transport = httpx2.MockTransport(handler)
    real_client = httpx2.AsyncClient

    def factory(**kwargs):
        kwargs["transport"] = transport
        return real_client(**kwargs)

    monkeypatch.setattr(httpx2, "AsyncClient", factory)


def _google_prm(scopes) -> dict:
    return {
        "resource": BIGQUERY_URL,
        "authorization_servers": [GOOGLE_ISSUER],
        "scopes_supported": scopes,
    }


def _google_asm() -> dict:
    return {
        "issuer": GOOGLE_ISSUER,
        "authorization_endpoint": GOOGLE_AUTH_ENDPOINT,
        "token_endpoint": "https://oauth2.googleapis.com/token",
        "response_types_supported": ["code"],
    }


def _probe_must_not_be_sent(request: httpx2.Request) -> httpx2.Response:
    """The probe is answered with a synthetic 401 and must never hit the wire.

    Regression guard for the BigQuery case: the server returns 200 to an
    unauthenticated initialize, so a real probe would see no challenge and the
    flow would never start.
    """
    raise AssertionError(f"probe request must not be sent: {request.url}")


_PROBE = f"POST {BIGQUERY_URL}"
_PRM_PATH = (
    "GET https://bigquery.googleapis.com/.well-known/oauth-protected-resource/mcp"
)
_ASM_ROOT = f"GET {GOOGLE_ISSUER.rstrip('/')}/.well-known/oauth-authorization-server"


async def test_uses_scopes_discovered_from_prm(monkeypatch):
    # The scope advertised by the PRM must end up in the authorize URL.
    scope = "https://www.googleapis.com/auth/bigquery.readonly"
    _serve(
        monkeypatch,
        {
            _PROBE: _probe_must_not_be_sent,
            _PRM_PATH: _google_prm([scope]),
            _ASM_ROOT: _google_asm(),
        },
    )

    provider = _make_provider()
    with pytest.raises(OAuthAuthorizationRequired) as exc_info:
        await provider.initiate_authorization()

    storage = provider.context.storage
    # Everything the callback — a separate request with a fresh provider —
    # needs is persisted: the registration, the AS metadata, the verifier.
    assert storage.client_info.client_id == "client-123"
    assert str(storage.oauth_metadata.issuer) == GOOGLE_ISSUER
    state, verifier = storage.verifier

    parsed = urlparse(exc_info.value.url)
    query = parse_qs(parsed.query)

    # Authorize endpoint comes from discovered AS metadata, not server_url/authorize.
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == GOOGLE_AUTH_ENDPOINT
    assert query["state"] == [state]
    assert len(verifier) >= 43
    # Discovery sets the scope.
    assert query["scope"] == [scope]
    # RFC 8707 resource param fires because PRM is present.
    assert query["resource"] == [BIGQUERY_URL]
    # PKCE + the Google quirk (offline access on a consent screen).
    assert query["code_challenge_method"] == ["S256"]
    assert query["access_type"] == ["offline"]
    assert query["prompt"] == ["consent"]
    assert query["client_id"] == ["client-123"]
    assert query["response_type"] == ["code"]


async def test_omits_scope_param_when_prm_has_no_scopes(monkeypatch):
    # If the PRM advertises no scopes (and there is no WWW-Authenticate scope),
    # the authorize request omits scope entirely.
    _serve(
        monkeypatch,
        {
            _PROBE: _probe_must_not_be_sent,
            _PRM_PATH: _google_prm(None),
            _ASM_ROOT: _google_asm(),
        },
    )

    with pytest.raises(OAuthAuthorizationRequired) as exc_info:
        await _make_provider().initiate_authorization()

    query = parse_qs(urlparse(exc_info.value.url).query)
    assert "scope" not in query


async def test_authorize_url_falls_back_when_as_metadata_missing(monkeypatch):
    # AS metadata discovery yields nothing -> context.oauth_metadata stays None.
    # The authorize URL falls back to {base}/authorize; the Google quirk does
    # not fire (no issuer); the RFC 8707 resource param still does (PRM present).
    _serve(
        monkeypatch,
        {
            _PROBE: _probe_must_not_be_sent,
            _PRM_PATH: _google_prm(["https://www.googleapis.com/auth/bigquery"]),
            # every ASM URL 404s
        },
    )

    with pytest.raises(OAuthAuthorizationRequired) as exc_info:
        await _make_provider().initiate_authorization()

    parsed = urlparse(exc_info.value.url)
    query = parse_qs(parsed.query)
    assert (
        f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        == "https://bigquery.googleapis.com/authorize"
    )
    assert "access_type" not in query
    assert query["resource"] == [BIGQUERY_URL]


async def test_gmail_keeps_its_fixed_scopes_over_discovery(monkeypatch):
    """The SDK's scope-selection step overwrites `client_metadata.scope` with
    what discovery found; the Gmail quirk must still win in the authorize URL."""
    gmail_url = "https://gmailmcp.googleapis.com/mcp/v1"
    _serve(
        monkeypatch,
        {
            f"POST {gmail_url}": _probe_must_not_be_sent,
            "GET https://gmailmcp.googleapis.com/.well-known/oauth-protected-resource/mcp/v1": {
                "resource": gmail_url,
                "authorization_servers": [GOOGLE_ISSUER],
                "scopes_supported": ["openid"],
            },
            _ASM_ROOT: _google_asm(),
        },
    )
    provider = WebOAuthClientProvider(
        server_url=gmail_url,
        client_metadata=build_oauth_client_metadata(),
        storage=_FakeStorage(),
        client_id="client-123",
        client_secret="secret-xyz",
    )

    with pytest.raises(OAuthAuthorizationRequired) as exc_info:
        await provider.initiate_authorization()

    query = parse_qs(urlparse(exc_info.value.url).query)
    assert "https://www.googleapis.com/auth/gmail.modify" in query["scope"][0]


async def test_dynamic_client_registration_when_no_static_creds(monkeypatch):
    # A server with no pre-registered credentials (e.g. Notion) must register
    # dynamically (RFC 7591) before the authorize URL can be built.
    notion_url = "https://mcp.notion.com/mcp"
    notion_issuer = "https://mcp.notion.com/"
    _serve(
        monkeypatch,
        {
            f"POST {notion_url}": _probe_must_not_be_sent,
            "GET https://mcp.notion.com/.well-known/oauth-protected-resource/mcp": {
                "resource": notion_url,
                "authorization_servers": [notion_issuer],
            },
            "GET https://mcp.notion.com/.well-known/oauth-authorization-server": {
                "issuer": notion_issuer,
                "authorization_endpoint": "https://mcp.notion.com/authorize",
                "token_endpoint": "https://mcp.notion.com/token",
                "registration_endpoint": "https://mcp.notion.com/register",
                "response_types_supported": ["code"],
            },
            "POST https://mcp.notion.com/register": httpx2.Response(
                201,
                json={
                    "client_id": "dcr-client-id",
                    "client_secret": "dcr-secret",
                    "token_endpoint_auth_method": "client_secret_post",
                    "redirect_uris": ["https://app.example/cb"],
                },
            ),
        },
    )

    # No client_id/secret -> forces dynamic registration.
    provider = WebOAuthClientProvider(
        server_url=notion_url,
        client_metadata=build_oauth_client_metadata(),
        storage=_FakeStorage(),
    )

    with pytest.raises(OAuthAuthorizationRequired) as exc_info:
        await provider.initiate_authorization()

    # The dynamically-registered client_id is used and persisted for the callback.
    assert provider.context.storage.client_info.client_id == "dcr-client-id"
    query = parse_qs(urlparse(exc_info.value.url).query)
    assert query["client_id"] == ["dcr-client-id"]
    # Notion advertises no scopes -> none requested.
    assert "scope" not in query


TIKTOK_URL = "https://business-api.tiktok.com/open_mcp/tt-ads-mcp-layer/oauth"
TIKTOK_BASE = "https://business-api.tiktok.com"


def _tiktok_register_handler(request: httpx2.Request) -> httpx2.Response:
    """Registers public clients only: rejects client_secret_post like TikTok."""
    body = json.loads(request.content.decode())
    if body.get("token_endpoint_auth_method") != "none":
        return httpx2.Response(400, json={"error": "invalid_client_metadata"})
    return httpx2.Response(
        201,
        json={
            "client_id": "tiktok-public",
            "token_endpoint_auth_method": "none",
            "redirect_uris": ["https://app.example/cb"],
        },
    )


async def test_recovery_uses_path_aware_as_metadata_and_public_dcr(monkeypatch):
    # TikTok publishes no RFC 9728 PRM, hosts its AS metadata at
    # {server_path}/.well-known/openid-configuration (which the SDK's root-only
    # fallback misses), and only registers public clients. The first attempt's
    # registration fails; _recover_registration_context must find the metadata
    # path-aware, negotiate "none", and the retry must succeed.
    _serve(
        monkeypatch,
        {
            f"POST {TIKTOK_URL}": _probe_must_not_be_sent,
            # no PRM, no root ASM (404 everywhere)
            f"GET {TIKTOK_URL}/.well-known/openid-configuration": {
                "issuer": f"{TIKTOK_URL}/",
                "authorization_endpoint": f"{TIKTOK_URL}/authorize",
                "token_endpoint": f"{TIKTOK_URL}/token",
                "registration_endpoint": f"{TIKTOK_BASE}/register",
                "token_endpoint_auth_methods_supported": ["none"],
                "response_types_supported": ["code"],
            },
            f"POST {TIKTOK_BASE}/register": _tiktok_register_handler,
        },
    )

    provider = WebOAuthClientProvider(
        server_url=TIKTOK_URL,
        client_metadata=build_oauth_client_metadata(),
        storage=_FakeStorage(),
    )
    with pytest.raises(OAuthAuthorizationRequired) as exc_info:
        await provider.initiate_authorization()

    assert provider.context.storage.client_info.client_id == "tiktok-public"
    query = parse_qs(urlparse(exc_info.value.url).query)
    assert query["client_id"] == ["tiktok-public"]


async def test_dcr_retries_as_public_client_for_none_only_server(monkeypatch):
    # Discovery works normally, but the server only registers public clients:
    # the first DCR (client_secret_post) is rejected, negotiation switches to
    # "none", and the retry registers successfully.
    _serve(
        monkeypatch,
        {
            f"POST {TIKTOK_URL}": _probe_must_not_be_sent,
            f"GET {TIKTOK_BASE}/.well-known/oauth-protected-resource/open_mcp/tt-ads-mcp-layer/oauth": {
                "resource": TIKTOK_URL,
                "authorization_servers": [f"{TIKTOK_URL}/"],
                "scopes_supported": ["mcp:tt4b"],
            },
            f"GET {TIKTOK_BASE}/.well-known/oauth-authorization-server/open_mcp/tt-ads-mcp-layer/oauth": {
                "issuer": f"{TIKTOK_URL}/",
                "authorization_endpoint": f"{TIKTOK_URL}/authorize",
                "token_endpoint": f"{TIKTOK_URL}/token",
                "registration_endpoint": f"{TIKTOK_BASE}/register",
                "token_endpoint_auth_methods_supported": ["none"],
                "response_types_supported": ["code"],
            },
            f"POST {TIKTOK_BASE}/register": _tiktok_register_handler,
        },
    )

    provider = WebOAuthClientProvider(
        server_url=TIKTOK_URL,
        client_metadata=build_oauth_client_metadata(),
        storage=_FakeStorage(),
    )
    with pytest.raises(OAuthAuthorizationRequired):
        await provider.initiate_authorization()

    assert provider.context.storage.client_info.client_id == "tiktok-public"
    assert provider.context.client_metadata.token_endpoint_auth_method == "none"


# ---------------------------------------------------------------------------
# The callback half: manual_exchange on a fresh provider
# ---------------------------------------------------------------------------


async def test_manual_exchange_finishes_from_persisted_state(monkeypatch):
    """The callback runs on a provider that never did discovery: everything it
    needs comes from storage, and the token lands back there."""
    seen: dict = {}

    def token_endpoint(request: httpx2.Request) -> httpx2.Response:
        seen["body"] = parse_qs(request.content.decode())
        return httpx2.Response(
            200,
            json={
                "access_token": "at",
                "token_type": "bearer",
                "expires_in": 3600,
                "refresh_token": "rt",
            },
        )

    _serve(monkeypatch, {"POST https://oauth2.googleapis.com/token": token_endpoint})

    storage = _FakeStorage()
    storage.oauth_metadata = OAuthMetadata(
        issuer=GOOGLE_ISSUER,
        authorization_endpoint=GOOGLE_AUTH_ENDPOINT,
        token_endpoint="https://oauth2.googleapis.com/token",
    )
    storage.client_info = OAuthClientInformationFull(
        client_id="client-123",
        client_secret="secret-xyz",
        redirect_uris=["https://app.example/cb"],
        token_endpoint_auth_method="client_secret_post",
    )
    storage.get_verifier = lambda state: _resolve(
        "verifier-abc" if state == "st" else None
    )  # type: ignore[attr-defined]
    storage.delete_verifier = lambda state: _resolve(seen.setdefault("deleted", state))  # type: ignore[attr-defined]

    provider = WebOAuthClientProvider(
        server_url=BIGQUERY_URL,
        client_metadata=build_oauth_client_metadata(),
        storage=storage,
    )
    await provider.manual_exchange("the-code", "st")

    assert seen["body"]["code"] == ["the-code"]
    assert seen["body"]["code_verifier"] == ["verifier-abc"]
    assert seen["body"]["client_secret"] == ["secret-xyz"]
    assert storage.tokens.access_token == "at"
    assert seen["deleted"] == "st"


async def test_manual_exchange_rejects_an_unknown_state():
    storage = _FakeStorage()
    storage.client_info = OAuthClientInformationFull(
        client_id="client-123", redirect_uris=["https://app.example/cb"]
    )
    storage.get_verifier = lambda state: _resolve(None)  # type: ignore[attr-defined]
    provider = WebOAuthClientProvider(
        server_url=BIGQUERY_URL,
        client_metadata=build_oauth_client_metadata(),
        storage=storage,
    )

    with pytest.raises(OAuthFlowError, match="invalid state"):
        await provider.manual_exchange("the-code", "stale")


async def _resolve(value):
    return value


# ---------------------------------------------------------------------------
# ensure_valid_token: a rejected refresh must not be retried forever
# ---------------------------------------------------------------------------


class _ExpiredTokenStorage(_FakeStorage):
    """Holds an expired-but-refreshable token until ``delete_tokens`` is called."""

    def __init__(self):
        super().__init__()
        self.stored = StoredToken(
            token_payload=OAuthToken(access_token="stale", refresh_token="rt"),
            expires_at=datetime.now(UTC) - timedelta(minutes=1),
        )

    async def get_stored_token(self):
        return self.stored

    async def delete_tokens(self):
        self.stored = None


def _expired_provider(monkeypatch, respond):
    """Provider holding an expired token; ``respond`` answers the refresh POST.
    Returns the provider and the list of requests that reached the token
    endpoint."""
    calls: list[httpx2.Request] = []

    def token_endpoint(request: httpx2.Request) -> httpx2.Response:
        calls.append(request)
        return respond(request)

    _serve(monkeypatch, {"POST https://oauth2.googleapis.com/token": token_endpoint})

    provider = WebOAuthClientProvider(
        server_url=BIGQUERY_URL,
        client_metadata=build_oauth_client_metadata(),
        storage=_ExpiredTokenStorage(),
        client_id="client-123",
        client_secret="secret-xyz",
    )
    provider._initialized = True
    provider.context.oauth_metadata = _asm()
    provider.context.client_info = OAuthClientInformationFull(
        client_id="client-123",
        client_secret="secret-xyz",
        redirect_uris=["https://app.example/cb"],
        token_endpoint_auth_method="client_secret_post",
    )
    provider.context.current_tokens = OAuthToken(
        access_token="stale", refresh_token="rt"
    )
    return provider, calls


@pytest.mark.parametrize("status", [400, 401, 403, 404, 302])
async def test_rejected_refresh_drops_stored_tokens(monkeypatch, status):
    """Metabase answers 400 for a revoked/rotated/expired refresh token; other
    servers use 401, 403 or non-standard codes. Keeping the pair would retry
    the dead token on every poll; drop it instead so the next check prompts a
    clean re-authorization."""
    provider, calls = _expired_provider(
        monkeypatch,
        lambda request: httpx2.Response(
            status, json={"error": "invalid_request"}, request=request
        ),
    )

    assert await provider.ensure_valid_token() is False
    assert await provider.context.storage.get_stored_token() is None
    # The pair is gone: the next check finds nothing stored and does not
    # hit the token endpoint again — that is what lets the UI re-prompt.
    assert await provider.ensure_valid_token() is False
    assert len(calls) == 1


@pytest.mark.parametrize("status", [429, 500, 502, 503, 599])
async def test_as_outage_on_refresh_keeps_stored_tokens(monkeypatch, status):
    """429 / 5xx say the AS is throttling or down, not that the credential is
    dead: keep the pair and retry on the next check. Only these keep it —
    see ``test_rejected_refresh_drops_stored_tokens`` for the rest."""
    provider, calls = _expired_provider(
        monkeypatch, lambda request: httpx2.Response(status, request=request)
    )

    assert await provider.ensure_valid_token() is False
    assert await provider.context.storage.get_stored_token() is not None
    assert await provider.ensure_valid_token() is False
    assert len(calls) == 2


@pytest.mark.parametrize("status", [202, 204])
async def test_unexpected_2xx_on_refresh_never_drops_stored_tokens(monkeypatch, status):
    """A 2xx the AS should not send (no parseable token body) is not a
    rejection: the pair survives and is retried, never deleted."""
    provider, calls = _expired_provider(
        monkeypatch, lambda request: httpx2.Response(status, request=request)
    )

    assert await provider.ensure_valid_token() is False
    assert await provider.context.storage.get_stored_token() is not None
    assert await provider.ensure_valid_token() is False
    assert len(calls) == 2


async def test_successful_refresh_stores_the_new_token(monkeypatch):
    provider, calls = _expired_provider(
        monkeypatch,
        lambda request: httpx2.Response(
            200,
            json={"access_token": "fresh", "token_type": "bearer", "expires_in": 3600},
            request=request,
        ),
    )

    assert await provider.ensure_valid_token() is True
    assert provider.context.storage.tokens.access_token == "fresh"
    assert len(calls) == 1


async def test_transport_failure_on_refresh_keeps_stored_tokens(monkeypatch):
    """A network error is not a rejection: the token pair must survive it."""

    def blow_up(request):
        raise httpx2.ConnectError("boom", request=request)

    provider, _calls = _expired_provider(monkeypatch, blow_up)

    assert await provider.ensure_valid_token() is False
    assert await provider.context.storage.get_stored_token() is not None


# ---------------------------------------------------------------------------
# token_endpoint_auth_method negotiation before dynamic registration
#
# We default to client_secret_post, but a public-only server (e.g. TikTok
# advertises token_endpoint_auth_methods_supported: ["none"]) rejects that with
# invalid_client_metadata. The requested method must be aligned with what the
# server supports before DCR.
# ---------------------------------------------------------------------------


def _provider_no_creds(url: str = TIKTOK_URL) -> WebOAuthClientProvider:
    return WebOAuthClientProvider(
        server_url=url,
        client_metadata=build_oauth_client_metadata(),
        storage=_FakeStorage(),
    )


def _asm_with_methods(methods) -> OAuthMetadata:
    return OAuthMetadata(
        issuer=f"{TIKTOK_URL}/",
        authorization_endpoint=f"{TIKTOK_URL}/authorize",
        token_endpoint=f"{TIKTOK_URL}/token",
        registration_endpoint=f"{TIKTOK_URL}/register",
        token_endpoint_auth_methods_supported=methods,
    )


def test_negotiate_prefers_none_for_public_only_server():
    # The TikTok case: only "none" offered -> client_secret_post must be dropped.
    provider = _provider_no_creds()
    provider.context.oauth_metadata = _asm_with_methods(["none"])
    provider._negotiate_registration_auth_method()
    assert provider.context.client_metadata.token_endpoint_auth_method == "none"


def test_negotiate_keeps_default_when_supported():
    provider = _provider_no_creds()
    provider.context.oauth_metadata = _asm_with_methods(["client_secret_post", "none"])
    provider._negotiate_registration_auth_method()
    assert (
        provider.context.client_metadata.token_endpoint_auth_method
        == "client_secret_post"
    )


def test_negotiate_keeps_default_when_server_omits_field():
    provider = _provider_no_creds()
    provider.context.oauth_metadata = _asm_with_methods(None)
    provider._negotiate_registration_auth_method()
    assert (
        provider.context.client_metadata.token_endpoint_auth_method
        == "client_secret_post"
    )


def test_negotiate_keeps_default_when_no_metadata():
    # AS metadata discovery found nothing at all (e.g. TikTok, which publishes
    # no PRM and hosts metadata under a non-standard path) -> oauth_metadata is
    # None. Negotiation must not raise AttributeError and keeps our default.
    provider = _provider_no_creds()
    provider.context.oauth_metadata = None
    provider._negotiate_registration_auth_method()
    assert (
        provider.context.client_metadata.token_endpoint_auth_method
        == "client_secret_post"
    )


def test_negotiate_falls_back_to_basic_when_only_basic():
    provider = _provider_no_creds()
    provider.context.oauth_metadata = _asm_with_methods(["client_secret_basic"])
    provider._negotiate_registration_auth_method()
    assert (
        provider.context.client_metadata.token_endpoint_auth_method
        == "client_secret_basic"
    )


def test_negotiate_raises_when_no_performable_method():
    # Server offers only methods this client can't perform (e.g. private_key_jwt)
    # -> raise instead of registering with a method that fails at token exchange.
    provider = _provider_no_creds()
    provider.context.oauth_metadata = _asm_with_methods(["private_key_jwt"])
    with pytest.raises(OAuthFlowError):
        provider._negotiate_registration_auth_method()


# ---------------------------------------------------------------------------
# Token requests for client_secret_basic registrations
#
# RFC 6749 §2.3 allows a single client-authentication method per request, but
# the SDK keeps client_id in the form body alongside the Basic Authorization
# header; strict servers (e.g. Notion) reject that as multiple authentication
# methods. The provider strips it so registrations stored as
# client_secret_basic keep working without re-registration.
# ---------------------------------------------------------------------------


def _asm() -> OAuthMetadata:
    return OAuthMetadata(
        issuer=GOOGLE_ISSUER,
        authorization_endpoint=GOOGLE_AUTH_ENDPOINT,
        token_endpoint="https://oauth2.googleapis.com/token",
    )


def _provider_with_client_info(auth_method: str) -> WebOAuthClientProvider:
    provider = _make_provider()
    provider.context.oauth_metadata = _asm()
    provider.context.client_info = OAuthClientInformationFull(
        client_id="client-123",
        client_secret="secret-xyz",
        redirect_uris=["https://app.example/cb"],
        token_endpoint_auth_method=auth_method,
    )
    return provider


async def test_exchange_request_for_basic_omits_client_id_in_body():
    provider = _provider_with_client_info("client_secret_basic")

    request = await provider._exchange_token_authorization_code(
        auth_code="code-abc", code_verifier="verifier"
    )

    assert request.headers["Authorization"].startswith("Basic ")
    body = parse_qs(request.content.decode())
    assert "client_id" not in body
    assert "client_secret" not in body
    assert body["code"] == ["code-abc"]
    assert body["grant_type"] == ["authorization_code"]


async def test_exchange_request_for_post_keeps_credentials_in_body():
    provider = _provider_with_client_info("client_secret_post")

    request = await provider._exchange_token_authorization_code(
        auth_code="code-abc", code_verifier="verifier"
    )

    assert "Authorization" not in request.headers
    body = parse_qs(request.content.decode())
    assert body["client_id"] == ["client-123"]
    assert body["client_secret"] == ["secret-xyz"]


async def test_refresh_request_for_basic_omits_client_id_in_body():
    provider = _provider_with_client_info("client_secret_basic")
    provider.context.current_tokens = OAuthToken(access_token="at", refresh_token="rt")

    request = await provider._refresh_token()

    assert request.headers["Authorization"].startswith("Basic ")
    body = parse_qs(request.content.decode())
    assert "client_id" not in body
    assert body["refresh_token"] == ["rt"]
    assert body["grant_type"] == ["refresh_token"]
