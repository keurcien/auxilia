"""Tests for the shared OAuth-provider construction in app/mcp/servers/service.py.

`_build_oauth_provider` is the single place that turns an OAuth2 MCP server into
a WebOAuthClientProvider (loading + decrypting static credentials); the three
former copies (handle_oauth_callback / initiate_oauth / connect_to_server) now
route through it.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from mcp.shared.auth import OAuthClientInformationFull

from app.mcp.servers import service as service_module
from app.mcp.servers.service import _build_oauth_provider


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
    monkeypatch.setattr(service_module, "decrypt_api_key", lambda _: "decrypted-secret")
    server = SimpleNamespace(id="s1", url="https://mcp.example.com/mcp")

    provider = await _build_oauth_provider(
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

    provider = await _build_oauth_provider(
        server, MagicMock(), _repo_without_credentials()
    )

    assert provider._client_id is None
    assert provider._client_secret is None


async def test_persist_client_info_writes_when_credentials_present(monkeypatch):
    monkeypatch.setattr(service_module, "decrypt_api_key", lambda _: "decrypted-secret")
    storage = MagicMock()
    storage.set_client_info = AsyncMock()
    server = SimpleNamespace(id="s1", url="https://mcp.example.com/mcp")

    provider = await _build_oauth_provider(server, storage, _repo_with_credentials())
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

    provider = await _build_oauth_provider(server, storage, _repo_without_credentials())
    await provider.persist_client_info()

    storage.set_client_info.assert_not_awaited()
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.exceptions import AlreadyExistsError, DomainValidationError
from app.mcp.servers.models import MCPAuthType
from app.mcp.servers.schemas import MCPServerCreate
from app.mcp.servers.service import MCPServerService


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
    repo.create = AsyncMock()
    repo.create_or_update_api_key = AsyncMock()
    repo.create_or_update_oauth_credentials = AsyncMock()
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
