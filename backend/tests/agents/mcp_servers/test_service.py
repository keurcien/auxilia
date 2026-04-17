from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.agents.mcp_servers.service import AgentMCPServerService
from app.agents.models import AgentMCPServerDB, ToolStatus
from app.agents.schemas import AgentMCPServerCreate, AgentMCPServerPatch
from app.exceptions import NotFoundError
from app.mcp.servers.models import MCPAuthType


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.delete = AsyncMock()
    db.execute = AsyncMock()
    return db


@pytest.fixture
def mock_repo():
    repo = MagicMock()
    repo.get = AsyncMock()
    repo.create = AsyncMock()
    repo.update = AsyncMock()
    repo.delete = AsyncMock()
    return repo


@pytest.fixture
def service(mock_db, mock_repo):
    svc = AgentMCPServerService(mock_db)
    svc.repository = mock_repo
    return svc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_link(**kwargs):
    defaults = dict(
        id=uuid4(),
        agent_id=uuid4(),
        mcp_server_id=uuid4(),
        tools=None,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    return AgentMCPServerDB(**{**defaults, **kwargs})


def make_mcp_server(auth_type=MCPAuthType.none, **kwargs):
    server = MagicMock()
    server.id = kwargs.get("id", uuid4())
    server.name = kwargs.get("name", "Test Server")
    server.url = kwargs.get("url", "https://mcp.example.com")
    server.auth_type = auth_type
    return server


_UNSET = object()


def make_mock_execute_result(*, rows=_UNSET, scalar=_UNSET, scalars_list=_UNSET):
    result = MagicMock()
    if rows is not _UNSET:
        result.all.return_value = rows
    if scalar is not _UNSET:
        result.scalar_one_or_none.return_value = scalar
    if scalars_list is not _UNSET:
        result.scalars.return_value.all.return_value = scalars_list
    return result


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------

async def test_update_raises_404_when_not_found(service, mock_repo):
    mock_repo.get.return_value = None

    with pytest.raises(NotFoundError) as exc_info:
        await service.update(uuid4(), uuid4(), AgentMCPServerPatch())

    assert exc_info.value.detail == "Agent MCP server not found"


async def test_update_merges_tools_with_existing(service, mock_repo):
    link = make_link(tools={"search": ToolStatus.always_allow})
    mock_repo.get.return_value = link
    mock_repo.update.return_value = link

    await service.update(
        link.agent_id,
        link.mcp_server_id,
        AgentMCPServerPatch(tools={"write": ToolStatus.needs_approval}),
    )

    update_schema = mock_repo.update.call_args[0][1]
    assert isinstance(update_schema, AgentMCPServerPatch)
    assert update_schema.tools == {
        "search": ToolStatus.always_allow,
        "write": ToolStatus.needs_approval,
    }


async def test_update_sets_tools_when_no_existing(service, mock_repo):
    link = make_link(tools=None)
    mock_repo.get.return_value = link
    mock_repo.update.return_value = link

    await service.update(
        link.agent_id,
        link.mcp_server_id,
        AgentMCPServerPatch(tools={"search": ToolStatus.always_allow}),
    )

    update_schema = mock_repo.update.call_args[0][1]
    assert isinstance(update_schema, AgentMCPServerPatch)
    assert update_schema.tools == {"search": ToolStatus.always_allow}


async def test_update_skips_merge_when_update_tools_is_none(service, mock_repo):
    link = make_link(tools={"search": ToolStatus.always_allow})
    mock_repo.get.return_value = link
    mock_repo.update.return_value = link

    await service.update(
        link.agent_id,
        link.mcp_server_id,
        AgentMCPServerPatch(tools=None),
    )

    update_schema = mock_repo.update.call_args[0][1]
    assert isinstance(update_schema, AgentMCPServerPatch)
    # tools is present but None — no merge happened
    assert update_schema.tools is None


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------

async def test_delete_delegates_to_repository(service, mock_repo):
    link = make_link()
    mock_repo.get.return_value = link

    await service.delete(link.agent_id, link.mcp_server_id)

    mock_repo.get.assert_awaited_once_with(link.agent_id, link.mcp_server_id)
    mock_repo.delete.assert_awaited_once_with(link)


async def test_delete_raises_404_when_not_found(service, mock_repo):
    mock_repo.get.return_value = None

    with pytest.raises(NotFoundError):
        await service.delete(uuid4(), uuid4())

    mock_repo.delete.assert_not_called()


# ---------------------------------------------------------------------------
# create_or_update
# ---------------------------------------------------------------------------

async def test_create_or_update_raises_404_when_server_not_found(service, mock_db):
    mock_db.execute.return_value = make_mock_execute_result(scalar=None)

    with pytest.raises(NotFoundError) as exc_info:
        await service.create_or_update(
            uuid4(), uuid4(), AgentMCPServerCreate(), "user-id"
        )

    assert "MCP server" in exc_info.value.detail


async def test_create_or_update_updates_tools_on_existing(service, mock_db, mock_repo):
    server = make_mcp_server()
    link = make_link(tools=None)
    mock_db.execute.return_value = make_mock_execute_result(scalar=server)
    mock_repo.get.return_value = link
    new_tools = {"search": ToolStatus.always_allow}

    result = await service.create_or_update(
        link.agent_id,
        server.id,
        AgentMCPServerCreate(tools=new_tools),
        "user-id",
    )

    assert link.tools == new_tools
    assert result is link


async def test_create_or_update_returns_existing_unchanged_when_no_tools(
    service, mock_db, mock_repo
):
    server = make_mcp_server()
    link = make_link(tools={"existing": ToolStatus.always_allow})
    mock_db.execute.return_value = make_mock_execute_result(scalar=server)
    mock_repo.get.return_value = link

    result = await service.create_or_update(
        link.agent_id,
        server.id,
        AgentMCPServerCreate(tools=None),
        "user-id",
    )

    # No commit should happen when tools=None and link exists
    assert result is link
    assert result.tools == {"existing": ToolStatus.always_allow}


async def test_create_or_update_creates_and_fetches_tools_for_no_auth(
    service, mock_db, mock_repo
):
    server = make_mcp_server(auth_type=MCPAuthType.none)
    link = make_link()
    mock_db.execute.return_value = make_mock_execute_result(scalar=server)
    mock_repo.get.return_value = None
    mock_repo.create.return_value = link

    with patch.object(service, "_fetch_and_save_tools", new=AsyncMock()) as mock_fetch:
        await service.create_or_update(
            uuid4(), server.id, AgentMCPServerCreate(), "user-id"
        )

    mock_repo.create.assert_awaited_once()
    mock_fetch.assert_awaited_once_with(link, server, "user-id")


async def test_create_or_update_creates_and_fetches_tools_for_api_key(
    service, mock_db, mock_repo
):
    server = make_mcp_server(auth_type=MCPAuthType.api_key)
    link = make_link()
    mock_db.execute.return_value = make_mock_execute_result(scalar=server)
    mock_repo.get.return_value = None
    mock_repo.create.return_value = link

    with patch.object(service, "_fetch_and_save_tools", new=AsyncMock()) as mock_fetch:
        await service.create_or_update(
            uuid4(), server.id, AgentMCPServerCreate(), "user-id"
        )

    mock_fetch.assert_awaited_once()


async def test_create_or_update_oauth_fetches_tools_when_connected(
    service, mock_db, mock_repo
):
    server = make_mcp_server(auth_type=MCPAuthType.oauth2)
    link = make_link()
    mock_db.execute.return_value = make_mock_execute_result(scalar=server)
    mock_repo.get.return_value = None
    mock_repo.create.return_value = link

    with (
        patch(
            "app.agents.mcp_servers.service.check_oauth_connected",
            new=AsyncMock(return_value=True),
        ),
        patch.object(service, "_fetch_and_save_tools", new=AsyncMock()) as mock_fetch,
    ):
        await service.create_or_update(
            uuid4(), server.id, AgentMCPServerCreate(), "user-id"
        )

    mock_fetch.assert_awaited_once()


async def test_create_or_update_oauth_skips_fetch_when_not_connected(
    service, mock_db, mock_repo
):
    server = make_mcp_server(auth_type=MCPAuthType.oauth2)
    link = make_link()
    mock_db.execute.return_value = make_mock_execute_result(scalar=server)
    mock_repo.get.return_value = None
    mock_repo.create.return_value = link

    with (
        patch(
            "app.agents.mcp_servers.service.check_oauth_connected",
            new=AsyncMock(return_value=False),
        ),
        patch.object(service, "_fetch_and_save_tools", new=AsyncMock()) as mock_fetch,
    ):
        await service.create_or_update(
            uuid4(), server.id, AgentMCPServerCreate(), "user-id"
        )

    mock_fetch.assert_not_awaited()


# ---------------------------------------------------------------------------
# sync_tools
# ---------------------------------------------------------------------------

async def test_sync_tools_raises_404_when_server_not_found(service, mock_db):
    mock_db.execute.return_value = make_mock_execute_result(scalar=None)

    with pytest.raises(NotFoundError) as exc_info:
        await service.sync_tools(uuid4(), uuid4(), "user-id")

    assert "MCP server" in exc_info.value.detail


async def test_sync_tools_raises_404_when_link_not_found(service, mock_db, mock_repo):
    server = make_mcp_server()
    mock_db.execute.return_value = make_mock_execute_result(scalar=server)
    mock_repo.get.return_value = None

    with pytest.raises(NotFoundError) as exc_info:
        await service.sync_tools(uuid4(), server.id, "user-id")

    assert "Agent MCP server" in exc_info.value.detail


async def test_sync_tools_calls_fetch_and_save_and_returns_link(
    service, mock_db, mock_repo
):
    server = make_mcp_server()
    link = make_link()
    mock_db.execute.return_value = make_mock_execute_result(scalar=server)
    mock_repo.get.return_value = link

    with patch.object(service, "_fetch_and_save_tools", new=AsyncMock()) as mock_fetch:
        result = await service.sync_tools(uuid4(), server.id, "user-id")

    mock_fetch.assert_awaited_once_with(link, server, "user-id")
    assert result is link
