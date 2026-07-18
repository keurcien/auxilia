"""Tests for MCPServerRepository.update_oauth_credentials — the partial patch
that lets the edit form change client_id while keeping the stored secret.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from app.mcp.servers.repository import MCPServerRepository


def _repo() -> MCPServerRepository:
    return MCPServerRepository(AsyncMock())


async def test_blank_secret_keeps_existing_and_patches_client_id():
    creds = SimpleNamespace(
        client_id="old-id",
        client_secret_encrypted="enc-old",
        token_endpoint_auth_method=None,
    )
    repo = _repo()
    repo.get_oauth_credentials = AsyncMock(return_value=creds)

    await repo.update_oauth_credentials(uuid4(), client_id="new-id", client_secret=None)

    assert creds.client_id == "new-id"
    assert creds.client_secret_encrypted == "enc-old"  # untouched


async def test_secret_update_reencrypts(monkeypatch):
    import app.mcp.servers.repository as repo_module

    monkeypatch.setattr(repo_module, "encrypt_api_key", lambda v: f"enc:{v}")
    creds = SimpleNamespace(
        client_id="id",
        client_secret_encrypted="enc-old",
        token_endpoint_auth_method=None,
    )
    repo = _repo()
    repo.get_oauth_credentials = AsyncMock(return_value=creds)

    await repo.update_oauth_credentials(uuid4(), client_secret="fresh-secret")

    assert creds.client_secret_encrypted == "enc:fresh-secret"
    assert creds.client_id == "id"  # unchanged


async def test_no_existing_credentials_and_client_id_only_is_noop():
    repo = _repo()
    repo.get_oauth_credentials = AsyncMock(return_value=None)
    repo.create_or_update_oauth_credentials = AsyncMock()

    await repo.update_oauth_credentials(uuid4(), client_id="only-id")

    # Can't create without a secret, so nothing is written.
    repo.create_or_update_oauth_credentials.assert_not_awaited()


async def test_no_existing_credentials_with_both_creates():
    repo = _repo()
    repo.get_oauth_credentials = AsyncMock(return_value=None)
    repo.create_or_update_oauth_credentials = AsyncMock()

    sid = uuid4()
    await repo.update_oauth_credentials(sid, client_id="id", client_secret="sec")

    repo.create_or_update_oauth_credentials.assert_awaited_once_with(
        sid, "id", "sec", None
    )
