"""`resolve_transport_auth` — the single auth-type → transport dispatch.

Two implementations used to answer this question (the client-config factory and
the handshake path) and they had drifted: the factory raised on an unknown auth
type while the handshake silently connected *unauthenticated*, and both wrote a
missing API key into the header as the literal `Bearer None` (design review
§4.1). These tests pin both fixes, and that the memo actually memoizes.
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.exceptions import DomainValidationError
from app.mcp.client.connectivity import (
    CredentialCache,
    TransportAuth,
    resolve_transport_auth,
)
from app.mcp.servers.models import MCPAuthType, MCPServerDB


def _server(auth_type, **kwargs) -> MCPServerDB:
    return MCPServerDB(
        id=kwargs.pop("id", uuid4()),
        name=kwargs.pop("name", "Example"),
        url=kwargs.pop("url", "https://mcp.example.com"),
        auth_type=auth_type,
        **kwargs,
    )


def _repository(*, api_key=None, oauth=None) -> MagicMock:
    repo = MagicMock()
    repo.get_api_key = AsyncMock(return_value=api_key)
    repo.get_oauth_credentials = AsyncMock(return_value=oauth)
    return repo


async def test_no_auth_sends_nothing():
    auth = await resolve_transport_auth(_server(MCPAuthType.none), "u1", _repository())

    assert auth.headers is None and auth.auth is None
    assert auth.as_kwargs() == {}


async def test_api_key_becomes_a_bearer_header():
    auth = await resolve_transport_auth(
        _server(MCPAuthType.api_key), "u1", _repository(api_key="secret")
    )

    assert auth.as_kwargs() == {"headers": {"Authorization": "Bearer secret"}}


async def test_a_missing_api_key_is_an_error_not_a_bearer_none():
    """The old code formatted `None` into the header and let the server answer
    with an opaque 401."""
    with pytest.raises(DomainValidationError, match="no API key stored"):
        await resolve_transport_auth(
            _server(MCPAuthType.api_key, name="Stripe"), "u1", _repository()
        )


async def test_an_unknown_auth_type_raises_instead_of_connecting_open():
    server = _server(MCPAuthType.none)
    object.__setattr__(server, "auth_type", "totally-new-scheme")

    with pytest.raises(DomainValidationError, match="Unsupported MCP auth type"):
        await resolve_transport_auth(server, "u1", _repository())


async def test_oauth_builds_a_provider_and_persists_static_registration():
    server = _server(MCPAuthType.oauth2)
    credentials = MagicMock()
    provider = MagicMock()
    provider.persist_client_info = AsyncMock()

    with (
        patch("app.mcp.client.connectivity.TokenStorageFactory"),
        patch(
            "app.mcp.client.connectivity.provider_with_credentials",
            return_value=provider,
        ) as build,
    ):
        auth = await resolve_transport_auth(
            server, "u1", _repository(oauth=credentials)
        )

    assert auth.auth is provider
    # The credential row reaches provider construction — the run path used to
    # build a provider with no static client id/secret at all.
    assert build.call_args.args[2] is credentials
    provider.persist_client_info.assert_awaited_once()


async def test_the_memo_reads_each_credential_once_per_run_graph():
    """A parent and its subagents bind the same server; the credential behind
    it is the same for all of them."""
    key_server = _server(MCPAuthType.api_key)
    oauth_server = _server(MCPAuthType.oauth2)
    repository = _repository(api_key="secret", oauth=MagicMock())
    memo = CredentialCache()

    with (
        patch("app.mcp.client.connectivity.TokenStorageFactory"),
        patch(
            "app.mcp.client.connectivity.provider_with_credentials",
            return_value=MagicMock(persist_client_info=AsyncMock()),
        ),
    ):
        for _ in range(3):
            await resolve_transport_auth(key_server, "u1", repository, credentials=memo)
            await resolve_transport_auth(
                oauth_server, "u1", repository, credentials=memo
            )

    repository.get_api_key.assert_awaited_once()
    repository.get_oauth_credentials.assert_awaited_once()


async def test_without_a_memo_every_call_reads():
    server = _server(MCPAuthType.api_key)
    repository = _repository(api_key="secret")

    for _ in range(2):
        await resolve_transport_auth(server, "u1", repository)

    assert repository.get_api_key.await_count == 2


async def test_oauth_providers_are_never_shared_between_calls():
    """Only reads are memoized: the provider is stateful and a run graph's
    sessions are opened concurrently."""
    server = _server(MCPAuthType.oauth2)
    repository = _repository(oauth=None)
    memo = CredentialCache()

    with (
        patch("app.mcp.client.connectivity.TokenStorageFactory"),
        patch(
            "app.mcp.client.connectivity.provider_with_credentials",
            side_effect=lambda *args, **kwargs: MagicMock(
                persist_client_info=AsyncMock()
            ),
        ),
    ):
        first = await resolve_transport_auth(server, "u1", repository, credentials=memo)
        second = await resolve_transport_auth(
            server, "u1", repository, credentials=memo
        )

    assert first.auth is not second.auth


# ---------------------------------------------------------------------------
# connect_to_server — the handshake path uses the same seam
# ---------------------------------------------------------------------------


async def test_connect_to_server_hands_the_resolved_auth_to_the_session():
    """The handshake used to carry its own auth-type branch; the only thing it
    should do now is splat what the seam resolved."""
    from contextlib import asynccontextmanager

    from app.mcp.client import connectivity

    opened: dict = {}

    @asynccontextmanager
    async def _fake_open_session(url, **kwargs):
        opened["url"] = url
        opened["kwargs"] = kwargs
        yield ("session", [])

    with (
        patch.object(connectivity, "_open_session", _fake_open_session),
        patch.object(connectivity, "MCPServerRepository"),
        patch.object(
            connectivity,
            "resolve_transport_auth",
            new=AsyncMock(
                return_value=TransportAuth(headers={"Authorization": "Bearer k"})
            ),
        ),
    ):
        server = _server(MCPAuthType.api_key)
        async with connectivity.connect_to_server(server, "u1", MagicMock()) as result:
            assert result == ("session", [])

    assert opened["url"] == server.url
    assert opened["kwargs"]["headers"] == {"Authorization": "Bearer k"}
    assert opened["kwargs"]["terminate_on_close"] is True


async def test_connect_to_server_opens_nothing_when_the_credential_is_missing():
    """An api_key server with no stored key must fail before the handshake,
    not connect with `Bearer None` and get an opaque 401 back."""
    from app.mcp.client import connectivity

    with (
        patch.object(connectivity, "_open_session") as open_session,
        patch.object(connectivity, "MCPServerRepository", return_value=_repository()),
        pytest.raises(DomainValidationError),
    ):
        async with connectivity.connect_to_server(
            _server(MCPAuthType.api_key), "u1", MagicMock()
        ):
            pass

    open_session.assert_not_called()
