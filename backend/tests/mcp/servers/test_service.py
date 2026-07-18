"""Tests for the shared OAuth-provider construction in app/mcp/client/connectivity.py.

`build_oauth_provider` is the single place that turns an OAuth2 MCP server into
a WebOAuthClientProvider (loading + decrypting static credentials); every other
path (handshake / callback / authorization / refresh) routes through it.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from mcp.shared.auth import OAuthClientInformationFull

from app.exceptions import AlreadyExistsError, DomainValidationError
from app.mcp.client import connectivity as connectivity_module
from app.mcp.client.connectivity import build_oauth_provider
from app.mcp.servers import service as service_module
from app.mcp.servers.models import MCPAuthType
from app.mcp.servers.schemas import MCPServerCreate
from app.mcp.servers.service import MCPServerService


def _repo_with_credentials(**overrides):
    fields = {
        "client_id": "cid",
        "client_secret_encrypted": "enc",
        "token_endpoint_auth_method": None,
    }
    fields.update(overrides)
    repo = MagicMock()
    repo.get_oauth_credentials = AsyncMock(return_value=SimpleNamespace(**fields))
    return repo


def _repo_without_credentials():
    repo = MagicMock()
    repo.get_oauth_credentials = AsyncMock(return_value=None)
    return repo


async def test_build_oauth_provider_loads_static_credentials(monkeypatch):
    monkeypatch.setattr(
        connectivity_module, "decrypt_api_key", lambda _: "decrypted-secret"
    )
    server = SimpleNamespace(id="s1", url="https://mcp.example.com/mcp")

    provider = await build_oauth_provider(
        server,
        MagicMock(),
        _repo_with_credentials(token_endpoint_auth_method="client_secret_basic"),
    )

    assert provider._client_id == "cid"
    assert provider._client_secret == "decrypted-secret"
    assert (
        provider.context.client_metadata.token_endpoint_auth_method
        == "client_secret_basic"
    )


async def test_build_oauth_provider_without_credentials_defers_to_dcr():
    server = SimpleNamespace(id="s1", url="https://mcp.notion.com/mcp")

    provider = await build_oauth_provider(
        server, MagicMock(), _repo_without_credentials()
    )

    assert provider._client_id is None
    assert provider._client_secret is None
    # Requested explicitly at registration: omitting it lets servers default
    # to client_secret_basic, whose SDK token request Notion rejects.
    assert (
        provider.context.client_metadata.token_endpoint_auth_method
        == "client_secret_post"
    )


async def test_persist_client_info_writes_when_credentials_present(monkeypatch):
    monkeypatch.setattr(
        connectivity_module, "decrypt_api_key", lambda _: "decrypted-secret"
    )
    storage = MagicMock()
    storage.set_client_info = AsyncMock()
    server = SimpleNamespace(id="s1", url="https://mcp.example.com/mcp")

    provider = await build_oauth_provider(server, storage, _repo_with_credentials())
    await provider.persist_client_info()

    storage.set_client_info.assert_awaited_once()
    persisted = storage.set_client_info.call_args.args[0]
    assert isinstance(persisted, OAuthClientInformationFull)
    assert persisted.client_id == "cid"
    assert persisted.client_secret == "decrypted-secret"


async def test_persist_client_info_noop_without_credentials():
    storage = MagicMock()
    storage.set_client_info = AsyncMock()
    server = SimpleNamespace(id="s1", url="https://mcp.notion.com/mcp")

    provider = await build_oauth_provider(server, storage, _repo_without_credentials())
    await provider.persist_client_info()

    storage.set_client_info.assert_not_awaited()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.execute = AsyncMock()
    return db


@pytest.fixture
def mock_repo():
    repo = MagicMock()
    repo.get_by_url = AsyncMock()
    repo.get = AsyncMock()
    repo.create = AsyncMock()
    repo.update = AsyncMock()
    repo.create_or_update_api_key = AsyncMock()
    repo.create_or_update_oauth_credentials = AsyncMock()
    repo.update_oauth_credentials = AsyncMock()
    repo.get_oauth_credentials = AsyncMock()
    return repo


@pytest.fixture
def service(mock_db, mock_repo):
    svc = MCPServerService(mock_db)
    svc.repository = mock_repo
    return svc


def make_mcp_server(**kwargs):
    server = MagicMock()
    server.id = kwargs.get("id", uuid4())
    server.url = kwargs.get("url", "https://mcp.example.com/mcp")
    return server


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------


async def test_create_raises_already_exists_when_url_taken(service, mock_repo):
    mock_repo.get_by_url.return_value = make_mcp_server()

    data = MCPServerCreate(name="Duplicate", url="https://mcp.example.com/mcp")
    with pytest.raises(AlreadyExistsError) as exc_info:
        await service.create(data)

    assert exc_info.value.detail == "An MCP server with this URL already exists"
    mock_repo.create.assert_not_called()


async def test_create_succeeds_when_url_is_new(service, mock_repo):
    mock_repo.get_by_url.return_value = None
    created = make_mcp_server()
    mock_repo.create.return_value = created

    data = MCPServerCreate(name="Fresh", url="https://fresh.example.com/mcp")
    result = await service.create(data)

    assert result is created
    mock_repo.create.assert_awaited_once()


async def test_create_checks_duplicate_before_validating_auth(service, mock_repo):
    """A duplicate URL is reported as a conflict even if other fields are invalid."""
    mock_repo.get_by_url.return_value = make_mcp_server()

    # api_key auth without a key would normally raise DomainValidationError,
    # but the duplicate check runs first.
    data = MCPServerCreate(
        name="Duplicate",
        url="https://mcp.example.com/mcp",
        auth_type=MCPAuthType.api_key,
    )
    with pytest.raises(AlreadyExistsError):
        await service.create(data)


async def test_create_still_validates_api_key_for_new_url(service, mock_repo):
    mock_repo.get_by_url.return_value = None

    data = MCPServerCreate(
        name="Fresh",
        url="https://fresh.example.com/mcp",
        auth_type=MCPAuthType.api_key,
    )
    with pytest.raises(DomainValidationError):
        await service.create(data)

    mock_repo.create.assert_not_called()


# ---------------------------------------------------------------------------
# update — partial OAuth credentials
# ---------------------------------------------------------------------------


async def test_update_patches_client_id_without_secret(service, mock_repo):
    # Editing the client_id while leaving the secret blank must patch client_id
    # and pass client_secret=None so the stored secret is kept.
    from app.mcp.servers.schemas import MCPServerPatch

    server = make_mcp_server()
    server.auth_type = MCPAuthType.oauth2
    mock_repo.get.return_value = server
    mock_repo.update.return_value = server

    await service.update(server.id, MCPServerPatch(oauth_client_id="new-client-id"))

    mock_repo.update_oauth_credentials.assert_awaited_once()
    kwargs = mock_repo.update_oauth_credentials.await_args.kwargs
    assert kwargs["client_id"] == "new-client-id"
    assert kwargs["client_secret"] is None


async def test_update_skips_oauth_when_no_credential_fields(service, mock_repo):
    from app.mcp.servers.schemas import MCPServerPatch

    server = make_mcp_server()
    server.auth_type = MCPAuthType.oauth2
    mock_repo.get.return_value = server
    mock_repo.update.return_value = server

    await service.update(server.id, MCPServerPatch(name="Renamed"))

    mock_repo.update_oauth_credentials.assert_not_awaited()


# ---------------------------------------------------------------------------
# to_response — exposes client_id, never the secret
# ---------------------------------------------------------------------------


def _server_db(auth_type):
    from datetime import UTC, datetime

    from app.mcp.servers.models import MCPServerDB

    now = datetime(2026, 1, 1, tzinfo=UTC)
    return MCPServerDB(
        name="srv",
        url="https://mcp.example.com/mcp",
        auth_type=auth_type,
        created_at=now,
        updated_at=now,
    )


async def test_to_response_includes_oauth_client_id(service, mock_repo):
    server = _server_db(MCPAuthType.oauth2)
    mock_repo.get_oauth_credentials.return_value = SimpleNamespace(client_id="cid-123")

    response = await service.to_response(server)

    assert response.oauth_client_id == "cid-123"
    # The secret is never part of the response shape.
    assert not hasattr(response, "oauth_client_secret")


async def test_to_response_omits_client_id_for_non_oauth(service, mock_repo):
    server = _server_db(MCPAuthType.none)

    response = await service.to_response(server)

    assert response.oauth_client_id is None
    mock_repo.get_oauth_credentials.assert_not_awaited()


# ---------------------------------------------------------------------------
# get_oauth_secret_hint — last4 + length, never the full secret
# ---------------------------------------------------------------------------


async def test_secret_hint_returns_last4_and_length(service, mock_repo, monkeypatch):
    monkeypatch.setattr(
        service_module, "decrypt_value", lambda _: "supersecretvalue1234"
    )
    mock_repo.get_oauth_credentials.return_value = SimpleNamespace(
        client_secret_encrypted="enc"
    )

    hint = await service.get_oauth_secret_hint(uuid4())

    assert hint.is_set is True
    assert hint.last4 == "1234"
    assert hint.length == len("supersecretvalue1234")


async def test_secret_hint_not_set_when_no_credentials(service, mock_repo):
    mock_repo.get_oauth_credentials.return_value = None

    hint = await service.get_oauth_secret_hint(uuid4())

    assert hint.is_set is False
    assert hint.last4 is None
    assert hint.length is None


async def test_secret_hint_omits_last4_for_short_secret(
    service, mock_repo, monkeypatch
):
    # Secrets shorter than 10 chars expose length only, never a suffix.
    monkeypatch.setattr(service_module, "decrypt_value", lambda _: "short1")
    mock_repo.get_oauth_credentials.return_value = SimpleNamespace(
        client_secret_encrypted="enc"
    )

    hint = await service.get_oauth_secret_hint(uuid4())

    assert hint.is_set is True
    assert hint.last4 is None
    assert hint.length == len("short1")


async def test_secret_hint_404_for_missing_server(service, mock_repo):
    from app.exceptions import NotFoundError

    mock_repo.get.return_value = None  # get_or_404 -> NotFoundError

    with pytest.raises(NotFoundError):
        await service.get_oauth_secret_hint(uuid4())


async def test_update_persists_auth_method_only(service, mock_repo):
    from app.mcp.servers.schemas import MCPServerPatch

    server = make_mcp_server()
    server.auth_type = MCPAuthType.oauth2
    mock_repo.get.return_value = server
    mock_repo.update.return_value = server

    await service.update(
        server.id,
        MCPServerPatch(oauth_token_endpoint_auth_method="client_secret_basic"),
    )

    mock_repo.update_oauth_credentials.assert_awaited_once()
    assert (
        mock_repo.update_oauth_credentials.await_args.kwargs["auth_method"]
        == "client_secret_basic"
    )
