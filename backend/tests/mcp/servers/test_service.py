"""Tests for the shared OAuth-provider construction in app/mcp/servers/service.py.

`_build_oauth_provider` is the single place that turns an OAuth2 MCP server into
a WebOAuthClientProvider (loading + decrypting static credentials); the three
former copies (handle_oauth_callback / _initiate_oauth / connect_to_server) now
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
