from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.agents.core.service import AgentService
from app.agents.models import (
    AgentDB,
    AgentMCPServerDB,
    PermissionLevel,
    ToolStatus,
)
from app.agents.schemas import AgentCreateDB, AgentPatch, AgentResponse
from app.exceptions import NotFoundError
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
    db.flush = AsyncMock()
    return db


@pytest.fixture
def mock_repo():
    repo = MagicMock()
    repo.get = AsyncMock()
    repo.create = AsyncMock()
    repo.update = AsyncMock()
    repo.archive = AsyncMock()
    repo.get_permissions = AsyncMock()
    repo.set_permissions = AsyncMock()
    repo.list_with_permissions = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def mock_subagent_service():
    svc = MagicMock()
    svc.load_subagents = AsyncMock(return_value=[])
    svc.load_all_subagent_data = AsyncMock(return_value=({}, set()))
    svc.delete_all_for_agent = AsyncMock()
    svc.repository = MagicMock()
    svc.repository.is_subagent = AsyncMock(return_value=False)
    return svc


@pytest.fixture
def service(mock_db, mock_repo, mock_subagent_service):
    svc = AgentService(mock_db)
    svc.repository = mock_repo
    svc.subagent_service = mock_subagent_service
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


_UNSET = object()


def _make_mock_execute_result(*, rows=_UNSET, scalar=_UNSET, scalars_list=_UNSET):
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
    data = AgentCreateDB(name="X", instructions="Y", owner_id=uuid4())

    result = await service.create_agent(data)

    mock_repo.create.assert_awaited_once_with(data)
    assert result is agent


# ---------------------------------------------------------------------------
# get_agent
# ---------------------------------------------------------------------------

async def test_get_agent_returns_agent_read(service, mock_repo):
    agent = make_agent()
    mock_repo.list_with_permissions.return_value = [(agent, None)]

    result = await service.get_agent(agent.id)

    assert isinstance(result, AgentResponse)
    assert result.id == agent.id
    assert result.name == agent.name
    assert result.mcp_servers == []
    assert result.current_user_permission is None


async def test_get_agent_raises_404_when_not_found(service, mock_repo):
    mock_repo.list_with_permissions.return_value = []

    with pytest.raises(NotFoundError) as exc_info:
        await service.get_agent(uuid4())

    assert exc_info.value.detail == "Agent not found"


async def test_get_agent_sets_owner_permission(service, mock_repo):
    owner_id = uuid4()
    agent = make_agent(owner_id=owner_id)
    mock_repo.list_with_permissions.return_value = [(agent, None)]

    result = await service.get_agent(agent.id, user_id=owner_id)

    assert result.current_user_permission == "owner"


async def test_get_agent_sets_admin_permission(service, mock_repo):
    agent = make_agent()
    mock_repo.list_with_permissions.return_value = [(agent, None)]

    result = await service.get_agent(agent.id, user_role=WorkspaceRole.admin)

    assert result.current_user_permission == "admin"


async def test_get_agent_includes_mcp_servers_from_bindings(service, mock_repo):
    agent = make_agent()
    server_id = uuid4()
    tools = {"search": ToolStatus.always_allow}
    binding = AgentMCPServerDB(
        id=uuid4(),
        agent_id=agent.id,
        mcp_server_id=server_id,
        tools=tools,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    mock_repo.list_with_permissions.return_value = [(agent, binding)]

    result = await service.get_agent(agent.id)

    assert len(result.mcp_servers) == 1
    assert result.mcp_servers[0].mcp_server_id == server_id
    assert result.mcp_servers[0].tools == tools


async def test_get_agent_skips_null_bindings(service, mock_repo):
    agent = make_agent()
    mock_repo.list_with_permissions.return_value = [(agent, None)]

    result = await service.get_agent(agent.id)

    assert result.mcp_servers == []


# ---------------------------------------------------------------------------
# list_agents
# ---------------------------------------------------------------------------

async def test_list_agents_returns_empty_when_no_agents(service, mock_repo):
    mock_repo.list_with_permissions.return_value = []

    result = await service.list_agents()

    assert result == []


async def test_list_agents_returns_one_per_agent(service, mock_repo):
    agent = make_agent()
    mock_repo.list_with_permissions.return_value = [(agent, None)]

    result = await service.list_agents()

    assert len(result) == 1
    assert result[0].id == agent.id


async def test_list_agents_deduplicates_multiple_bindings_per_agent(service, mock_repo):
    agent = make_agent()
    binding1 = AgentMCPServerDB(
        id=uuid4(), agent_id=agent.id, mcp_server_id=uuid4(),
        tools=None, created_at=datetime.now(), updated_at=datetime.now(),
    )
    binding2 = AgentMCPServerDB(
        id=uuid4(), agent_id=agent.id, mcp_server_id=uuid4(),
        tools=None, created_at=datetime.now(), updated_at=datetime.now(),
    )
    mock_repo.list_with_permissions.return_value = [(agent, binding1), (agent, binding2)]

    result = await service.list_agents(user_role=WorkspaceRole.admin)

    assert len(result) == 1
    assert len(result[0].mcp_servers) == 2


async def test_list_agents_owner_gets_owner_permission(service, mock_repo):
    owner_id = uuid4()
    agent = make_agent(owner_id=owner_id)
    mock_repo.list_with_permissions.return_value = [(agent, None, None)]

    result = await service.list_agents(user_id=owner_id, user_role=WorkspaceRole.member)

    assert result[0].current_user_permission == "owner"


async def test_list_agents_admin_gets_admin_permission(service, mock_repo):
    agent = make_agent()
    mock_repo.list_with_permissions.return_value = [(agent, None)]

    result = await service.list_agents(user_role=WorkspaceRole.admin)

    assert result[0].current_user_permission == "admin"


async def test_list_agents_granted_permission_from_row(service, mock_repo):
    agent = make_agent()
    non_owner_id = uuid4()
    mock_repo.list_with_permissions.return_value = [
        (agent, None, PermissionLevel.editor)
    ]

    result = await service.list_agents(user_id=non_owner_id, user_role=WorkspaceRole.member)

    assert result[0].current_user_permission == "editor"


async def test_list_agents_no_permission_when_not_granted(service, mock_repo):
    agent = make_agent()
    non_owner_id = uuid4()
    mock_repo.list_with_permissions.return_value = [(agent, None, None)]

    result = await service.list_agents(user_id=non_owner_id, user_role=WorkspaceRole.member)

    assert result[0].current_user_permission is None


async def test_list_agents_no_user_returns_agents_with_no_permission(service, mock_repo):
    agent = make_agent()
    mock_repo.list_with_permissions.return_value = [(agent, None)]

    result = await service.list_agents()

    assert result[0].current_user_permission is None


# ---------------------------------------------------------------------------
# update_agent
# ---------------------------------------------------------------------------

async def test_update_agent_delegates_to_repository(service, mock_repo):
    agent = make_agent()
    mock_repo.get.return_value = agent
    mock_repo.list_with_permissions.return_value = [(agent, None)]

    result = await service.update_agent(agent.id, AgentPatch(name="Updated"))

    mock_repo.get.assert_awaited_once_with(agent.id)
    call_args = mock_repo.update.call_args[0]
    assert call_args[0] is agent
    assert isinstance(call_args[1], AgentPatch)
    assert call_args[1].name == "Updated"
    assert isinstance(result, AgentResponse)
    assert result.id == agent.id
    assert result.mcp_servers == []


async def test_update_agent_passes_only_set_fields(service, mock_repo):
    agent = make_agent()
    mock_repo.get.return_value = agent
    mock_repo.list_with_permissions.return_value = [(agent, None)]

    await service.update_agent(agent.id, AgentPatch(name="New Name"))

    update_schema = mock_repo.update.call_args[0][1]
    assert isinstance(update_schema, AgentPatch)
    assert update_schema.model_dump(exclude_unset=True) == {"name": "New Name"}


async def test_update_agent_raises_404_when_not_found(service, mock_repo):
    mock_repo.get.return_value = None

    with pytest.raises(NotFoundError) as exc_info:
        await service.update_agent(uuid4(), AgentPatch(name="X"))

    assert exc_info.value.detail == "Agent not found"
    mock_repo.update.assert_not_called()


# ---------------------------------------------------------------------------
# delete_agent
# ---------------------------------------------------------------------------

async def test_delete_agent_delegates_to_repository(service, mock_repo, mock_subagent_service):
    agent = make_agent()
    mock_repo.get.return_value = agent

    await service.delete_agent(agent.id)

    mock_repo.get.assert_awaited_once_with(agent.id)
    mock_subagent_service.delete_all_for_agent.assert_awaited_once_with(agent.id)
    mock_repo.archive.assert_awaited_once_with(agent)


async def test_delete_agent_raises_404_when_not_found(service, mock_repo):
    mock_repo.get.return_value = None

    with pytest.raises(NotFoundError) as exc_info:
        await service.delete_agent(uuid4())

    assert exc_info.value.detail == "Agent not found"
    mock_repo.archive.assert_not_called()


# ---------------------------------------------------------------------------
# check_ready
# ---------------------------------------------------------------------------

async def test_check_ready_returns_ready_when_no_mcp_servers(service, mock_repo):
    agent = make_agent()
    mock_repo.list_with_permissions.return_value = [(agent, None)]

    result = await service.check_ready(agent.id, "user-id")

    assert result["ready"] is True
    assert result["status"] == "ready"
    assert result["disconnected_servers"] == []


async def test_check_ready_returns_not_configured_when_tools_is_none(service, mock_repo):
    agent = make_agent()
    server_id = uuid4()
    binding = AgentMCPServerDB(
        id=uuid4(),
        agent_id=agent.id,
        mcp_server_id=server_id,
        tools=None,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    mock_repo.list_with_permissions.return_value = [(agent, binding)]

    result = await service.check_ready(agent.id, "user-id")

    assert result["ready"] is False
    assert result["status"] == "not_configured"


async def test_check_ready_returns_ready_when_all_servers_connected(service, mock_db, mock_repo):
    agent = make_agent()
    server_id = uuid4()
    binding = AgentMCPServerDB(
        id=uuid4(),
        agent_id=agent.id,
        mcp_server_id=server_id,
        tools={"search": ToolStatus.always_allow},
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    mcp_server = MagicMock()
    mcp_server.id = server_id

    mock_repo.list_with_permissions.return_value = [(agent, binding)]
    mock_db.execute.return_value = _make_mock_execute_result(scalars_list=[mcp_server])

    with patch(
        "app.agents.core.service.check_mcp_server_connected",
        new=AsyncMock(return_value=True),
    ):
        result = await service.check_ready(agent.id, "user-id")

    assert result["ready"] is True
    assert result["disconnected_servers"] == []


async def test_check_ready_returns_not_ready_when_server_disconnected(service, mock_db, mock_repo):
    agent = make_agent()
    server_id = uuid4()
    binding = AgentMCPServerDB(
        id=uuid4(),
        agent_id=agent.id,
        mcp_server_id=server_id,
        tools={"search": ToolStatus.always_allow},
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    mcp_server = MagicMock()
    mcp_server.id = server_id

    mock_repo.list_with_permissions.return_value = [(agent, binding)]
    mock_db.execute.return_value = _make_mock_execute_result(scalars_list=[mcp_server])

    with patch(
        "app.agents.core.service.check_mcp_server_connected",
        new=AsyncMock(return_value=False),
    ):
        result = await service.check_ready(agent.id, "user-id")

    assert result["ready"] is False
    assert str(server_id) in result["disconnected_servers"]


async def test_check_ready_disconnected_status_label(service, mock_db, mock_repo):
    agent = make_agent()
    server_id = uuid4()
    binding = AgentMCPServerDB(
        id=uuid4(),
        agent_id=agent.id,
        mcp_server_id=server_id,
        tools={"x": ToolStatus.always_allow},
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    mcp_server = MagicMock()
    mcp_server.id = server_id

    mock_repo.list_with_permissions.return_value = [(agent, binding)]
    mock_db.execute.return_value = _make_mock_execute_result(scalars_list=[mcp_server])

    with patch(
        "app.agents.core.service.check_mcp_server_connected",
        new=AsyncMock(return_value=False),
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
