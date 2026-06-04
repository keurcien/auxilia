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
