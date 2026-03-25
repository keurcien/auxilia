from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.agents.mcp_servers.service import MCPBindingService
from app.agents.models import (
    AgentMCPServerBindingCreate,
    AgentMCPServerBindingDB,
    AgentMCPServerBindingUpdate,
    ToolStatus,
)
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
    repo.get_binding = AsyncMock()
    repo.create_binding = AsyncMock()
    repo.update_binding = AsyncMock()
    repo.delete_binding = AsyncMock()
    return repo


@pytest.fixture
def service(mock_db, mock_repo):
    svc = MCPBindingService(mock_db)
    svc.repository = mock_repo
    return svc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_binding(**kwargs):
    defaults = dict(
        id=uuid4(),
        agent_id=uuid4(),
        mcp_server_id=uuid4(),
        tools=None,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    return AgentMCPServerBindingDB(**{**defaults, **kwargs})


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
# update_binding
# ---------------------------------------------------------------------------

async def test_update_binding_raises_404_when_not_found(service, mock_repo):
    mock_repo.get_binding.return_value = None

    with pytest.raises(HTTPException) as exc_info:
        await service.update_binding(uuid4(), uuid4(), AgentMCPServerBindingUpdate())

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Binding not found"


async def test_update_binding_merges_tools_with_existing(service, mock_repo):
    binding = make_binding(tools={"search": ToolStatus.always_allow})
    mock_repo.get_binding.return_value = binding
    mock_repo.update_binding.return_value = binding

    await service.update_binding(
        binding.agent_id,
        binding.mcp_server_id,
        AgentMCPServerBindingUpdate(tools={"write": ToolStatus.needs_approval}),
    )

    update_data = mock_repo.update_binding.call_args[0][1]
    assert update_data["tools"] == {
        "search": ToolStatus.always_allow,
        "write": ToolStatus.needs_approval,
    }


async def test_update_binding_sets_tools_when_no_existing(service, mock_repo):
    binding = make_binding(tools=None)
    mock_repo.get_binding.return_value = binding
    mock_repo.update_binding.return_value = binding

    await service.update_binding(
        binding.agent_id,
        binding.mcp_server_id,
        AgentMCPServerBindingUpdate(tools={"search": ToolStatus.always_allow}),
    )

    update_data = mock_repo.update_binding.call_args[0][1]
    assert update_data["tools"] == {"search": ToolStatus.always_allow}


async def test_update_binding_skips_merge_when_update_tools_is_none(service, mock_repo):
    binding = make_binding(tools={"search": ToolStatus.always_allow})
    mock_repo.get_binding.return_value = binding
    mock_repo.update_binding.return_value = binding

    await service.update_binding(
        binding.agent_id,
        binding.mcp_server_id,
        AgentMCPServerBindingUpdate(tools=None),
    )

    update_data = mock_repo.update_binding.call_args[0][1]
    # tools key is present but None — no merge happened
    assert update_data.get("tools") is None


# ---------------------------------------------------------------------------
# delete_binding
# ---------------------------------------------------------------------------

async def test_delete_binding_delegates_to_repository(service, mock_repo):
    binding = make_binding()
    mock_repo.get_binding.return_value = binding

    await service.delete_binding(binding.agent_id, binding.mcp_server_id)

    mock_repo.get_binding.assert_awaited_once_with(binding.agent_id, binding.mcp_server_id)
    mock_repo.delete_binding.assert_awaited_once_with(binding)


async def test_delete_binding_raises_404_when_not_found(service, mock_repo):
    mock_repo.get_binding.return_value = None

    with pytest.raises(HTTPException) as exc_info:
        await service.delete_binding(uuid4(), uuid4())

    assert exc_info.value.status_code == 404
    mock_repo.delete_binding.assert_not_called()


# ---------------------------------------------------------------------------
# create_or_update_binding
# ---------------------------------------------------------------------------

async def test_create_or_update_binding_raises_404_when_server_not_found(service, mock_db):
    mock_db.execute.return_value = make_mock_execute_result(scalar=None)

    with pytest.raises(HTTPException) as exc_info:
        await service.create_or_update_binding(
            uuid4(), uuid4(), AgentMCPServerBindingCreate(), "user-id"
        )

    assert exc_info.value.status_code == 404
    assert "MCP server" in exc_info.value.detail


async def test_create_or_update_binding_updates_tools_on_existing(service, mock_db, mock_repo):
    server = make_mcp_server()
    binding = make_binding(tools=None)
    mock_db.execute.return_value = make_mock_execute_result(scalar=server)
    mock_repo.get_binding.return_value = binding
    new_tools = {"search": ToolStatus.always_allow}

    result = await service.create_or_update_binding(
        binding.agent_id,
        server.id,
        AgentMCPServerBindingCreate(tools=new_tools),
        "user-id",
    )

    assert binding.tools == new_tools
    assert result is binding


async def test_create_or_update_binding_returns_existing_unchanged_when_no_tools(
    service, mock_db, mock_repo
):
    server = make_mcp_server()
    binding = make_binding(tools={"existing": ToolStatus.always_allow})
    mock_db.execute.return_value = make_mock_execute_result(scalar=server)
    mock_repo.get_binding.return_value = binding

    result = await service.create_or_update_binding(
        binding.agent_id,
        server.id,
        AgentMCPServerBindingCreate(tools=None),
        "user-id",
    )

    # No commit should happen when tools=None and binding exists
    assert result is binding
    assert result.tools == {"existing": ToolStatus.always_allow}


async def test_create_or_update_binding_creates_and_fetches_tools_for_no_auth(
    service, mock_db, mock_repo
):
    server = make_mcp_server(auth_type=MCPAuthType.none)
    binding = make_binding()
    mock_db.execute.return_value = make_mock_execute_result(scalar=server)
    mock_repo.get_binding.return_value = None
    mock_repo.create_binding.return_value = binding

    with patch.object(service, "_fetch_and_save_tools", new=AsyncMock()) as mock_fetch:
        await service.create_or_update_binding(
            uuid4(), server.id, AgentMCPServerBindingCreate(), "user-id"
        )

    mock_repo.create_binding.assert_awaited_once()
    mock_fetch.assert_awaited_once_with(binding, server, "user-id")


async def test_create_or_update_binding_creates_and_fetches_tools_for_api_key(
    service, mock_db, mock_repo
):
    server = make_mcp_server(auth_type=MCPAuthType.api_key)
    binding = make_binding()
    mock_db.execute.return_value = make_mock_execute_result(scalar=server)
    mock_repo.get_binding.return_value = None
    mock_repo.create_binding.return_value = binding

    with patch.object(service, "_fetch_and_save_tools", new=AsyncMock()) as mock_fetch:
        await service.create_or_update_binding(
            uuid4(), server.id, AgentMCPServerBindingCreate(), "user-id"
        )

    mock_fetch.assert_awaited_once()


async def test_create_or_update_binding_oauth_fetches_tools_when_connected(
    service, mock_db, mock_repo
):
    server = make_mcp_server(auth_type=MCPAuthType.oauth2)
    binding = make_binding()
    mock_db.execute.return_value = make_mock_execute_result(scalar=server)
    mock_repo.get_binding.return_value = None
    mock_repo.create_binding.return_value = binding

    with (
        patch.object(service, "_check_oauth_connected", new=AsyncMock(return_value=True)),
        patch.object(service, "_fetch_and_save_tools", new=AsyncMock()) as mock_fetch,
    ):
        await service.create_or_update_binding(
            uuid4(), server.id, AgentMCPServerBindingCreate(), "user-id"
        )

    mock_fetch.assert_awaited_once()


async def test_create_or_update_binding_oauth_skips_fetch_when_not_connected(
    service, mock_db, mock_repo
):
    server = make_mcp_server(auth_type=MCPAuthType.oauth2)
    binding = make_binding()
    mock_db.execute.return_value = make_mock_execute_result(scalar=server)
    mock_repo.get_binding.return_value = None
    mock_repo.create_binding.return_value = binding

    with (
        patch.object(service, "_check_oauth_connected", new=AsyncMock(return_value=False)),
        patch.object(service, "_fetch_and_save_tools", new=AsyncMock()) as mock_fetch,
    ):
        await service.create_or_update_binding(
            uuid4(), server.id, AgentMCPServerBindingCreate(), "user-id"
        )

    mock_fetch.assert_not_awaited()


# ---------------------------------------------------------------------------
# sync_tools
# ---------------------------------------------------------------------------

async def test_sync_tools_raises_404_when_server_not_found(service, mock_db):
    mock_db.execute.return_value = make_mock_execute_result(scalar=None)

    with pytest.raises(HTTPException) as exc_info:
        await service.sync_tools(uuid4(), uuid4(), "user-id")

    assert exc_info.value.status_code == 404
    assert "MCP server" in exc_info.value.detail


async def test_sync_tools_raises_404_when_binding_not_found(service, mock_db, mock_repo):
    server = make_mcp_server()
    mock_db.execute.return_value = make_mock_execute_result(scalar=server)
    mock_repo.get_binding.return_value = None

    with pytest.raises(HTTPException) as exc_info:
        await service.sync_tools(uuid4(), server.id, "user-id")

    assert exc_info.value.status_code == 404
    assert "Binding" in exc_info.value.detail


async def test_sync_tools_calls_fetch_and_save_and_returns_binding(
    service, mock_db, mock_repo
):
    server = make_mcp_server()
    binding = make_binding()
    mock_db.execute.return_value = make_mock_execute_result(scalar=server)
    mock_repo.get_binding.return_value = binding

    with patch.object(service, "_fetch_and_save_tools", new=AsyncMock()) as mock_fetch:
        result = await service.sync_tools(uuid4(), server.id, "user-id")

    mock_fetch.assert_awaited_once_with(binding, server, "user-id")
    assert result is binding
