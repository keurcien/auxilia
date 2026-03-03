from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.agents.models import (
    AgentCreate,
    AgentDB,
    AgentMCPServerBindingCreate,
    AgentMCPServerBindingDB,
    AgentMCPServerBindingUpdate,
    AgentPermissionWrite,
    AgentRead,
    AgentUpdate,
    AgentUserPermissionDB,
    PermissionLevel,
    ToolStatus,
)
from app.agents.service import AgentService
from app.mcp.servers.models import MCPAuthType
from app.users.models import WorkspaceRole


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
    repo.get_binding = AsyncMock()
    repo.create_binding = AsyncMock()
    repo.update_binding = AsyncMock()
    repo.delete_binding = AsyncMock()
    repo.get_permissions = AsyncMock()
    repo.set_permissions = AsyncMock()
    return repo


@pytest.fixture
def service(mock_db, mock_repo):
    svc = AgentService(mock_db)
    svc.repository = mock_repo
    return svc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_agent(**kwargs):
    defaults = dict(
        id=uuid4(),
        name="Test Agent",
        instructions="Be helpful",
        owner_id=uuid4(),
        emoji=None,
        description=None,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    return AgentDB(**{**defaults, **kwargs})


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
    """Build a mock db.execute() result supporting .all(), .scalar_one_or_none(), .scalars().all().

    Use explicit keyword args to control which method is set. Passing scalar=None
    correctly configures scalar_one_or_none() to return None.
    """
    result = MagicMock()
    if rows is not _UNSET:
        result.all.return_value = rows
    if scalar is not _UNSET:
        result.scalar_one_or_none.return_value = scalar
    if scalars_list is not _UNSET:
        result.scalars.return_value.all.return_value = scalars_list
    return result


# ---------------------------------------------------------------------------
# create_agent
# ---------------------------------------------------------------------------

async def test_create_agent_delegates_to_repository(service, mock_repo):
    agent = make_agent()
    mock_repo.create.return_value = agent
    data = AgentCreate(name="X", instructions="Y", owner_id=uuid4())

    result = await service.create_agent(data)

    mock_repo.create.assert_awaited_once_with(data)
    assert result is agent


# ---------------------------------------------------------------------------
# get_agent
# ---------------------------------------------------------------------------

async def test_get_agent_returns_agent_read(service, mock_db):
    agent = make_agent()
    mock_db.execute.return_value = make_mock_execute_result(rows=[(agent, None)])

    result = await service.get_agent(agent.id)

    assert isinstance(result, AgentRead)
    assert result.id == agent.id
    assert result.name == agent.name
    assert result.mcp_servers == []
    assert result.current_user_permission is None


async def test_get_agent_raises_404_when_not_found(service, mock_db):
    mock_db.execute.return_value = make_mock_execute_result(rows=[])

    with pytest.raises(HTTPException) as exc_info:
        await service.get_agent(uuid4())

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Agent not found"


async def test_get_agent_sets_owner_permission(service, mock_db):
    owner_id = uuid4()
    agent = make_agent(owner_id=owner_id)
    mock_db.execute.return_value = make_mock_execute_result(rows=[(agent, None)])

    result = await service.get_agent(agent.id, user_id=owner_id)

    assert result.current_user_permission == "owner"


async def test_get_agent_sets_admin_permission(service, mock_db):
    agent = make_agent()
    mock_db.execute.return_value = make_mock_execute_result(rows=[(agent, None)])

    result = await service.get_agent(agent.id, user_role=WorkspaceRole.admin)

    assert result.current_user_permission == "admin"


async def test_get_agent_queries_db_for_granted_permission(service, mock_db):
    agent = make_agent()
    non_owner_id = uuid4()

    rows_result = make_mock_execute_result(rows=[(agent, None)])
    perm_result = make_mock_execute_result(scalar=PermissionLevel.editor)
    mock_db.execute.side_effect = [rows_result, perm_result]

    result = await service.get_agent(agent.id, user_id=non_owner_id)

    assert result.current_user_permission == "editor"
    assert mock_db.execute.await_count == 2


async def test_get_agent_returns_none_permission_when_not_granted(service, mock_db):
    agent = make_agent()
    non_owner_id = uuid4()

    rows_result = make_mock_execute_result(rows=[(agent, None)])
    perm_result = make_mock_execute_result(scalar=None)
    mock_db.execute.side_effect = [rows_result, perm_result]

    result = await service.get_agent(agent.id, user_id=non_owner_id)

    assert result.current_user_permission is None


async def test_get_agent_includes_mcp_servers_from_bindings(service, mock_db):
    agent = make_agent()
    server_id = uuid4()
    tools = {"search": ToolStatus.always_allow}
    binding = AgentMCPServerBindingDB(
        id=uuid4(),
        agent_id=agent.id,
        mcp_server_id=server_id,
        tools=tools,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    mock_db.execute.return_value = make_mock_execute_result(rows=[(agent, binding)])

    result = await service.get_agent(agent.id)

    assert len(result.mcp_servers) == 1
    assert result.mcp_servers[0].id == server_id
    assert result.mcp_servers[0].tools == tools


async def test_get_agent_skips_null_bindings(service, mock_db):
    agent = make_agent()
    mock_db.execute.return_value = make_mock_execute_result(rows=[(agent, None)])

    result = await service.get_agent(agent.id)

    assert result.mcp_servers == []


# ---------------------------------------------------------------------------
# list_agents
# ---------------------------------------------------------------------------

async def test_list_agents_returns_empty_when_no_agents(service, mock_db):
    mock_db.execute.return_value = make_mock_execute_result(rows=[])

    result = await service.list_agents()

    assert result == []


async def test_list_agents_returns_one_per_agent(service, mock_db):
    agent = make_agent()
    mock_db.execute.return_value = make_mock_execute_result(rows=[(agent, None)])

    result = await service.list_agents()

    assert len(result) == 1
    assert result[0].id == agent.id


async def test_list_agents_deduplicates_multiple_bindings_per_agent(service, mock_db):
    agent = make_agent()
    binding1 = make_binding(agent_id=agent.id, mcp_server_id=uuid4())
    binding2 = make_binding(agent_id=agent.id, mcp_server_id=uuid4())
    mock_db.execute.return_value = make_mock_execute_result(
        rows=[(agent, binding1), (agent, binding2)]
    )

    result = await service.list_agents(user_role=WorkspaceRole.admin)

    assert len(result) == 1
    assert len(result[0].mcp_servers) == 2


async def test_list_agents_owner_gets_owner_permission(service, mock_db):
    owner_id = uuid4()
    agent = make_agent(owner_id=owner_id)
    mock_db.execute.return_value = make_mock_execute_result(
        rows=[(agent, None, None)]
    )

    result = await service.list_agents(user_id=owner_id, user_role=WorkspaceRole.member)

    assert result[0].current_user_permission == "owner"


async def test_list_agents_admin_gets_admin_permission(service, mock_db):
    agent = make_agent()
    mock_db.execute.return_value = make_mock_execute_result(rows=[(agent, None)])

    result = await service.list_agents(user_role=WorkspaceRole.admin)

    assert result[0].current_user_permission == "admin"


async def test_list_agents_granted_permission_from_row(service, mock_db):
    agent = make_agent()
    non_owner_id = uuid4()
    mock_db.execute.return_value = make_mock_execute_result(
        rows=[(agent, None, PermissionLevel.editor)]
    )

    result = await service.list_agents(user_id=non_owner_id, user_role=WorkspaceRole.member)

    assert result[0].current_user_permission == "editor"


async def test_list_agents_no_permission_when_not_granted(service, mock_db):
    agent = make_agent()
    non_owner_id = uuid4()
    mock_db.execute.return_value = make_mock_execute_result(
        rows=[(agent, None, None)]
    )

    result = await service.list_agents(user_id=non_owner_id, user_role=WorkspaceRole.member)

    assert result[0].current_user_permission is None


async def test_list_agents_no_user_returns_agents_with_no_permission(service, mock_db):
    agent = make_agent()
    mock_db.execute.return_value = make_mock_execute_result(rows=[(agent, None)])

    result = await service.list_agents()

    assert result[0].current_user_permission is None


# ---------------------------------------------------------------------------
# update_agent
# ---------------------------------------------------------------------------

async def test_update_agent_delegates_to_repository(service, mock_repo):
    agent = make_agent()
    updated = make_agent(id=agent.id, name="Updated")
    mock_repo.get.return_value = agent
    mock_repo.update.return_value = updated

    result = await service.update_agent(agent.id, AgentUpdate(name="Updated"))

    mock_repo.get.assert_awaited_once_with(agent.id)
    mock_repo.update.assert_awaited_once_with(agent, {"name": "Updated"})
    assert result is updated


async def test_update_agent_passes_only_set_fields(service, mock_repo):
    agent = make_agent()
    mock_repo.get.return_value = agent
    mock_repo.update.return_value = agent

    await service.update_agent(agent.id, AgentUpdate(name="New Name"))

    update_data = mock_repo.update.call_args[0][1]
    assert update_data == {"name": "New Name"}
    assert "instructions" not in update_data
    assert "emoji" not in update_data


async def test_update_agent_raises_404_when_not_found(service, mock_repo):
    mock_repo.get.return_value = None

    with pytest.raises(HTTPException) as exc_info:
        await service.update_agent(uuid4(), AgentUpdate(name="X"))

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Agent not found"
    mock_repo.update.assert_not_called()


# ---------------------------------------------------------------------------
# delete_agent
# ---------------------------------------------------------------------------

async def test_delete_agent_delegates_to_repository(service, mock_repo):
    agent = make_agent()
    mock_repo.get.return_value = agent

    await service.delete_agent(agent.id)

    mock_repo.get.assert_awaited_once_with(agent.id)
    mock_repo.delete.assert_awaited_once_with(agent)


async def test_delete_agent_raises_404_when_not_found(service, mock_repo):
    mock_repo.get.return_value = None

    with pytest.raises(HTTPException) as exc_info:
        await service.delete_agent(uuid4())

    assert exc_info.value.status_code == 404
    mock_repo.delete.assert_not_called()


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


# ---------------------------------------------------------------------------
# check_ready
# ---------------------------------------------------------------------------

async def test_check_ready_returns_ready_when_no_mcp_servers(service, mock_db):
    agent = make_agent()
    mock_db.execute.return_value = make_mock_execute_result(rows=[(agent, None)])

    result = await service.check_ready(agent.id, "user-id")

    assert result["ready"] is True
    assert result["status"] == "ready"
    assert result["disconnected_servers"] == []


async def test_check_ready_returns_not_configured_when_tools_is_none(service, mock_db):
    agent = make_agent()
    server_id = uuid4()
    binding = AgentMCPServerBindingDB(
        id=uuid4(),
        agent_id=agent.id,
        mcp_server_id=server_id,
        tools=None,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    mock_db.execute.return_value = make_mock_execute_result(rows=[(agent, binding)])

    result = await service.check_ready(agent.id, "user-id")

    assert result["ready"] is False
    assert result["status"] == "not_configured"


async def test_check_ready_returns_ready_when_all_servers_connected(service, mock_db):
    agent = make_agent()
    server_id = uuid4()
    binding = AgentMCPServerBindingDB(
        id=uuid4(),
        agent_id=agent.id,
        mcp_server_id=server_id,
        tools={"search": ToolStatus.always_allow},
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    mcp_server = make_mcp_server(id=server_id)

    rows_result = make_mock_execute_result(rows=[(agent, binding)])
    servers_result = make_mock_execute_result(scalars_list=[mcp_server])
    mock_db.execute.side_effect = [rows_result, servers_result]

    with patch(
        "app.agents.service.check_mcp_server_connected", new=AsyncMock(return_value=True)
    ):
        result = await service.check_ready(agent.id, "user-id")

    assert result["ready"] is True
    assert result["disconnected_servers"] == []


async def test_check_ready_returns_not_ready_when_server_disconnected(service, mock_db):
    agent = make_agent()
    server_id = uuid4()
    binding = AgentMCPServerBindingDB(
        id=uuid4(),
        agent_id=agent.id,
        mcp_server_id=server_id,
        tools={"search": ToolStatus.always_allow},
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    mcp_server = make_mcp_server(id=server_id)

    rows_result = make_mock_execute_result(rows=[(agent, binding)])
    servers_result = make_mock_execute_result(scalars_list=[mcp_server])
    mock_db.execute.side_effect = [rows_result, servers_result]

    with patch(
        "app.agents.service.check_mcp_server_connected", new=AsyncMock(return_value=False)
    ):
        result = await service.check_ready(agent.id, "user-id")

    assert result["ready"] is False
    assert str(server_id) in result["disconnected_servers"]


async def test_check_ready_disconnected_status_label(service, mock_db):
    agent = make_agent()
    server_id = uuid4()
    binding = AgentMCPServerBindingDB(
        id=uuid4(),
        agent_id=agent.id,
        mcp_server_id=server_id,
        tools={"x": ToolStatus.always_allow},
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    mcp_server = make_mcp_server(id=server_id)

    rows_result = make_mock_execute_result(rows=[(agent, binding)])
    servers_result = make_mock_execute_result(scalars_list=[mcp_server])
    mock_db.execute.side_effect = [rows_result, servers_result]

    with patch(
        "app.agents.service.check_mcp_server_connected", new=AsyncMock(return_value=False)
    ):
        result = await service.check_ready(agent.id, "user-id")

    assert result["status"] == "disconnected"


# ---------------------------------------------------------------------------
# _resolve_permission (unit tests for the private helper)
# ---------------------------------------------------------------------------

def test_resolve_permission_returns_owner_when_owner(service):
    owner_id = uuid4()
    agent = make_agent(owner_id=owner_id)

    result = service._resolve_permission(agent, owner_id, WorkspaceRole.member, {})

    assert result == "owner"


def test_resolve_permission_returns_admin_when_admin_role(service):
    agent = make_agent()

    result = service._resolve_permission(agent, uuid4(), WorkspaceRole.admin, {})

    assert result == "admin"


def test_resolve_permission_owner_takes_priority_over_admin(service):
    owner_id = uuid4()
    agent = make_agent(owner_id=owner_id)

    result = service._resolve_permission(agent, owner_id, WorkspaceRole.admin, {})

    assert result == "owner"


def test_resolve_permission_returns_granted_permission(service):
    agent = make_agent()
    granted = {agent.id: "editor"}

    result = service._resolve_permission(agent, uuid4(), WorkspaceRole.member, granted)

    assert result == "editor"


def test_resolve_permission_returns_none_when_no_match(service):
    agent = make_agent()

    result = service._resolve_permission(agent, uuid4(), WorkspaceRole.member, {})

    assert result is None


def test_resolve_permission_returns_none_when_no_user(service):
    agent = make_agent()

    result = service._resolve_permission(agent, None, None, {})

    assert result is None
