"""Tests for WebOAuthClientProvider.initiate_authorization.

The provider replaces the old "call a dummy tool to provoke a 401" probe: it
discovers OAuth metadata explicitly (RFC 9728 PRM + RFC 8414/OIDC AS metadata),
applies the discovered scopes, and raises OAuthAuthorizationRequired with the
authorize URL — all on the plain request stack (no MCP session / task group).
"""

from __future__ import annotations

from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from mcp.shared.auth import (
    OAuthClientInformationFull,
    OAuthMetadata,
    OAuthToken,
    ProtectedResourceMetadata,
)

from app.mcp.client import auth as auth_module
from app.mcp.client.auth import WebOAuthClientProvider, build_oauth_client_metadata
from app.mcp.client.exceptions import OAuthAuthorizationRequired


BIGQUERY_URL = "https://bigquery.googleapis.com/mcp"
GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"


class _FakeStorage:
    """Minimal TokenStorage: unauthenticated, records what gets persisted."""

    def __init__(self):
        self.client_info = None

    async def get_tokens(self):
        return None

    async def get_client_info(self):
        return self.client_info

    async def set_client_info(self, client_info):
        self.client_info = client_info

    async def get_oauth_metadata(self):
        return None

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


def _asm() -> OAuthMetadata:
    return OAuthMetadata(
        issuer="https://accounts.google.com/",
        authorization_endpoint=GOOGLE_AUTH_ENDPOINT,
        token_endpoint="https://oauth2.googleapis.com/token",
    )


def _patch_discovery(monkeypatch, prm, asm_result):
    """Stub the network: send() returns a sentinel, and the SDK parse helpers
    return the canned PRM / AS-metadata regardless of the response."""
    monkeypatch.setattr(httpx.AsyncClient, "send", AsyncMock(return_value=object()))
    monkeypatch.setattr(
        auth_module, "handle_protected_resource_response", AsyncMock(return_value=prm)
    )
    monkeypatch.setattr(
        auth_module, "handle_auth_metadata_response", AsyncMock(return_value=asm_result)
    )


async def test_uses_scopes_discovered_from_prm(monkeypatch):
    # The scope advertised by the PRM must end up in the authorize URL.
    prm = ProtectedResourceMetadata(
        resource=BIGQUERY_URL,
        authorization_servers=["https://accounts.google.com"],
        scopes_supported=["https://www.googleapis.com/auth/bigquery.readonly"],
    )
    _patch_discovery(monkeypatch, prm, (True, _asm()))

    provider = _make_provider()
    with pytest.raises(OAuthAuthorizationRequired) as exc_info:
        await provider.initiate_authorization()

    # client_info must be persisted so the OAuth callback — a separate request
    # with a fresh provider — can recover the client_id/secret from storage.
    assert provider.context.storage.client_info is not None
    assert provider.context.storage.client_info.client_id == "client-123"

    parsed = urlparse(exc_info.value.url)
    query = parse_qs(parsed.query)

    # Authorize endpoint comes from discovered AS metadata, not server_url/authorize.
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == GOOGLE_AUTH_ENDPOINT
    # Discovery overrides the hardcoded scope.
    assert query["scope"] == ["https://www.googleapis.com/auth/bigquery.readonly"]
    # RFC 8707 resource param fires because PRM is present (C.3).
    assert query["resource"] == [BIGQUERY_URL]
    # PKCE + Google offline-consent params.
    assert query["code_challenge_method"] == ["S256"]
    assert query["access_type"] == ["offline"]
    assert query["prompt"] == ["consent"]
    assert query["client_id"] == ["client-123"]
    assert query["response_type"] == ["code"]


async def test_omits_scope_param_when_prm_has_no_scopes(monkeypatch):
    # No hardcoded fallback anymore: if the PRM advertises no scopes (and there
    # is no WWW-Authenticate scope), the authorize request omits scope entirely.
    prm = ProtectedResourceMetadata(
        resource=BIGQUERY_URL,
        authorization_servers=["https://accounts.google.com"],
        scopes_supported=None,
    )
    _patch_discovery(monkeypatch, prm, (True, _asm()))

    with pytest.raises(OAuthAuthorizationRequired) as exc_info:
        await _make_provider().initiate_authorization()

    query = parse_qs(urlparse(exc_info.value.url).query)
    assert "scope" not in query


async def test_no_attribute_error_when_as_metadata_discovery_fails(monkeypatch):
    # AS metadata discovery yields nothing -> context.oauth_metadata stays None.
    # The hardened issuer guard must not raise AttributeError.
    prm = ProtectedResourceMetadata(
        resource=BIGQUERY_URL,
        authorization_servers=["https://accounts.google.com"],
        scopes_supported=["https://www.googleapis.com/auth/bigquery"],
    )
    _patch_discovery(monkeypatch, prm, (False, None))

    with pytest.raises(OAuthAuthorizationRequired) as exc_info:
        await _make_provider().initiate_authorization()

    query = parse_qs(urlparse(exc_info.value.url).query)
    # With no AS metadata, Google-specific params are skipped (guard short-circuits).
    assert "access_type" not in query
    # resource param still present (PRM available).
    assert query["resource"] == [BIGQUERY_URL]


async def test_dynamic_client_registration_when_no_static_creds(monkeypatch):
    # A server with no pre-registered credentials (e.g. Notion) must register
    # dynamically (RFC 7591) before the authorize URL can be built.
    notion_url = "https://mcp.notion.com/mcp"
    prm = ProtectedResourceMetadata(
        resource=notion_url,
        authorization_servers=["https://mcp.notion.com"],
        scopes_supported=None,
    )
    asm = OAuthMetadata(
        issuer="https://mcp.notion.com/",
        authorization_endpoint="https://mcp.notion.com/authorize",
        token_endpoint="https://mcp.notion.com/token",
        registration_endpoint="https://mcp.notion.com/register",
    )
    _patch_discovery(monkeypatch, prm, (True, asm))
    monkeypatch.setattr(
        auth_module,
        "handle_registration_response",
        AsyncMock(
            return_value=OAuthClientInformationFull(
                client_id="dcr-client-id",
                redirect_uris=["https://app.example/cb"],
            )
        ),
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


async def test_as_metadata_discovery_falls_back_to_path_aware_urls(monkeypatch):
    # TikTok publishes no RFC 9728 PRM (every PRM URL 404s) and hosts its AS
    # metadata at {server_path}/.well-known/openid-configuration. With PRM
    # discovery yielding no authorization server, the AS-metadata step must
    # still probe the path-aware OIDC suffix URL — not only the origin root —
    # otherwise oauth_metadata stays None and registration crashes / fails.
    tiktok_url = "https://business-api.tiktok.com/open_mcp/tt-ads-mcp-layer/oauth"

    probed: list[str] = []
    orig_request = auth_module.create_oauth_metadata_request

    def _record(url):
        probed.append(url)
        return orig_request(url)

    monkeypatch.setattr(auth_module, "create_oauth_metadata_request", _record)
    monkeypatch.setattr(httpx.AsyncClient, "send", AsyncMock(return_value=object()))
    # No PRM anywhere -> auth_server_url stays None.
    monkeypatch.setattr(
        auth_module, "handle_protected_resource_response", AsyncMock(return_value=None)
    )
    # We only assert which URLs get probed, so no AS metadata is "found".
    monkeypatch.setattr(
        auth_module,
        "handle_auth_metadata_response",
        AsyncMock(return_value=(True, None)),
    )
    monkeypatch.setattr(
        auth_module,
        "handle_registration_response",
        AsyncMock(
            return_value=OAuthClientInformationFull(
                client_id="dcr-client-id",
                redirect_uris=["https://app.example/cb"],
            )
        ),
    )

    provider = WebOAuthClientProvider(
        server_url=tiktok_url,
        client_metadata=build_oauth_client_metadata(),
        storage=_FakeStorage(),
    )
    with pytest.raises(OAuthAuthorizationRequired):
        await provider.initiate_authorization()

    # The path-aware OIDC suffix (where TikTok actually serves its metadata) was
    # probed, in addition to the origin-root URL the SDK helper generates alone.
    assert f"{tiktok_url}/.well-known/openid-configuration" in probed


# ---------------------------------------------------------------------------
# token_endpoint_auth_method negotiation before dynamic registration
#
# We default to client_secret_post, but a public-only server (e.g. TikTok
# advertises token_endpoint_auth_methods_supported: ["none"]) rejects that with
# invalid_client_metadata. The requested method must be aligned with what the
# server supports before DCR.
# ---------------------------------------------------------------------------


TIKTOK_URL = "https://business-api.tiktok.com/open_mcp/tt-ads-mcp-layer/oauth"


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
    from mcp.client.auth import OAuthFlowError

    provider = _provider_no_creds()
    provider.context.oauth_metadata = _asm_with_methods(["private_key_jwt"])
    with pytest.raises(OAuthFlowError):
        provider._negotiate_registration_auth_method()


async def test_dcr_registers_public_client_for_none_only_server(monkeypatch):
    # End-to-end: the metadata actually sent to the registration endpoint must
    # carry "none" for a public-only server, not our client_secret_post default.
    prm = ProtectedResourceMetadata(
        resource=TIKTOK_URL,
        authorization_servers=[TIKTOK_URL],
        scopes_supported=["mcp:tt4b"],
    )
    _patch_discovery(monkeypatch, prm, (True, _asm_with_methods(["none"])))

    captured: dict[str, str | None] = {}

    def _capture(oauth_metadata, client_metadata, base_url):
        captured["auth_method"] = client_metadata.token_endpoint_auth_method
        return object()  # send() is stubbed and ignores this

    monkeypatch.setattr(auth_module, "create_client_registration_request", _capture)
    monkeypatch.setattr(
        auth_module,
        "handle_registration_response",
        AsyncMock(
            return_value=OAuthClientInformationFull(
                client_id="tiktok-public",
                redirect_uris=["https://app.example/cb"],
                token_endpoint_auth_method="none",
            )
        ),
    )

    provider = _provider_no_creds()
    with pytest.raises(OAuthAuthorizationRequired):
        await provider.initiate_authorization()

    assert captured["auth_method"] == "none"


# ---------------------------------------------------------------------------
# Token requests for client_secret_basic registrations
#
# RFC 6749 §2.3 allows a single client-authentication method per request, but
# the SDK keeps client_id in the form body alongside the Basic Authorization
# header; strict servers (e.g. Notion) reject that as multiple authentication
# methods. The provider strips it so registrations stored as
# client_secret_basic keep working without re-registration.
# ---------------------------------------------------------------------------


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
