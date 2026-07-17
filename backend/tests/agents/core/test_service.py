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
from app.agents.schemas import (
    AgentConfig,
    AgentCreateDB,
    AgentMCPServerConfig,
    AgentPatch,
    AgentResponse,
)
from app.exceptions import NotFoundError, PermissionDeniedError
from app.tags.models import TagDB
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
    repo.restore = AsyncMock()
    repo.delete = AsyncMock()
    repo.delete_all_permissions = AsyncMock()
    repo.get_permissions = AsyncMock()
    repo.set_permissions = AsyncMock()
    repo.get_team_ids = AsyncMock(return_value=[])
    repo.set_teams = AsyncMock(return_value=[])
    repo.delete_all_teams = AsyncMock()
    repo.list_with_permissions = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def mock_thread_service():
    svc = MagicMock()
    svc.delete_rows_for_agent = AsyncMock(return_value=["t1", "t2"])
    svc.purge_checkpoints = AsyncMock()
    return svc


@pytest.fixture
def mock_agent_mcp_repo():
    repo = MagicMock()
    repo.delete_all_for_agent = AsyncMock()
    return repo


@pytest.fixture
def mock_subagent_service():
    svc = MagicMock()
    svc.list_subagents = AsyncMock(return_value=[])
    svc.list_all_subagent_data = AsyncMock(return_value=({}, set()))
    svc.delete_all_for_agent = AsyncMock()
    svc.set_for_supervisor = AsyncMock()
    svc.repository = MagicMock()
    svc.repository.is_subagent = AsyncMock(return_value=False)
    return svc


@pytest.fixture
def mock_mcp_server_service():
    svc = MagicMock()
    svc.set_for_agent = AsyncMock()
    return svc


@pytest.fixture
def mock_tag_service():
    svc = MagicMock()
    svc.get = AsyncMock()
    svc.list_by_ids = AsyncMock(return_value=[])
    return svc


@pytest.fixture
def mock_user_service():
    svc = MagicMock()
    svc.list_by_ids = AsyncMock(return_value=[])
    return svc


@pytest.fixture
def service(
    mock_db,
    mock_repo,
    mock_subagent_service,
    mock_thread_service,
    mock_tag_service,
    mock_user_service,
    mock_agent_mcp_repo,
    mock_mcp_server_service,
):
    svc = AgentService(mock_db)
    svc.repository = mock_repo
    svc.subagent_service = mock_subagent_service
    svc.thread_service = mock_thread_service
    svc.tag_service = mock_tag_service
    svc.user_service = mock_user_service
    svc.mcp_server_repository = mock_agent_mcp_repo
    svc.mcp_server_service = mock_mcp_server_service
    return svc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_agent(**kwargs):
    defaults = {
        "id": uuid4(),
        "name": "Test Agent",
        "instructions": "Be helpful",
        "owner_id": uuid4(),
        "emoji": None,
        "description": None,
        "created_at": datetime.now(),
        "updated_at": datetime.now(),
    }
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

    result = await service.create(data)

    mock_repo.create.assert_awaited_once_with(data)
    assert result is agent


async def test_create_from_config_orchestrates(
    service, mock_repo, mock_mcp_server_service, mock_subagent_service
):
    owner_id = uuid4()
    agent = make_agent(owner_id=owner_id)
    mock_repo.create.return_value = agent
    mock_repo.list_with_permissions.return_value = [(agent, None)]
    server_id = uuid4()
    sub_id = uuid4()
    config = AgentConfig(
        name="Drafted",
        instructions="Do things",
        description="From a draft",
        mcp_servers=[AgentMCPServerConfig(mcp_server_id=server_id, tools=None)],
        subagent_ids=[sub_id],
    )

    result = await service.create_from_config(
        config, owner_id=owner_id, user_role=WorkspaceRole.admin
    )

    create_schema = mock_repo.create.call_args[0][0]
    assert isinstance(create_schema, AgentCreateDB)
    assert create_schema.owner_id == owner_id
    assert create_schema.name == "Drafted"
    assert create_schema.description == "From a draft"
    mock_mcp_server_service.set_for_agent.assert_awaited_once_with(
        agent.id, config.mcp_servers
    )
    mock_subagent_service.set_for_supervisor.assert_awaited_once_with(
        agent.id, [sub_id], user_role=WorkspaceRole.admin
    )
    assert isinstance(result, AgentResponse)
    assert result.current_user_permission == "owner"


async def test_create_from_config_binding_failure_propagates(
    service, mock_repo, mock_mcp_server_service
):
    """An invalid binding aborts the whole create — the request transaction
    rolls back, so no stray agent is left behind."""
    agent = make_agent()
    mock_repo.create.return_value = agent
    mock_mcp_server_service.set_for_agent.side_effect = NotFoundError(
        "MCP server not found"
    )
    config = AgentConfig(
        name="Drafted",
        instructions="Do things",
        mcp_servers=[AgentMCPServerConfig(mcp_server_id=uuid4(), tools=None)],
    )

    with pytest.raises(NotFoundError):
        await service.create_from_config(config, owner_id=uuid4())


# ---------------------------------------------------------------------------
# get_agent
# ---------------------------------------------------------------------------


async def test_get_agent_returns_agent_read(service, mock_repo):
    agent = make_agent()
    mock_repo.list_with_permissions.return_value = [(agent, None)]

    result = await service.get(agent.id)

    assert isinstance(result, AgentResponse)
    assert result.id == agent.id
    assert result.name == agent.name
    assert result.mcp_servers == []
    assert result.current_user_permission is None


async def test_get_agent_raises_404_when_not_found(service, mock_repo):
    mock_repo.list_with_permissions.return_value = []

    with pytest.raises(NotFoundError) as exc_info:
        await service.get(uuid4())

    assert exc_info.value.detail == "Agent not found"


async def test_get_agent_sets_owner_permission(service, mock_repo):
    owner_id = uuid4()
    agent = make_agent(owner_id=owner_id)
    mock_repo.list_with_permissions.return_value = [(agent, None)]

    result = await service.get(agent.id, user_id=owner_id)

    assert result.current_user_permission == "owner"


async def test_get_agent_sets_admin_permission(service, mock_repo):
    agent = make_agent()
    mock_repo.list_with_permissions.return_value = [(agent, None)]

    result = await service.get(agent.id, user_role=WorkspaceRole.admin)

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

    result = await service.get(agent.id)

    assert len(result.mcp_servers) == 1
    assert result.mcp_servers[0].mcp_server_id == server_id
    assert result.mcp_servers[0].tools == tools


async def test_get_agent_skips_null_bindings(service, mock_repo):
    agent = make_agent()
    mock_repo.list_with_permissions.return_value = [(agent, None)]

    result = await service.get(agent.id)

    assert result.mcp_servers == []


# ---------------------------------------------------------------------------
# list_agents
# ---------------------------------------------------------------------------


async def test_list_agents_returns_empty_when_no_agents(service, mock_repo):
    mock_repo.list_with_permissions.return_value = []

    result = await service.list()

    assert result == []


async def test_list_agents_returns_one_per_agent(service, mock_repo):
    agent = make_agent()
    mock_repo.list_with_permissions.return_value = [(agent, None)]

    result = await service.list()

    assert len(result) == 1
    assert result[0].id == agent.id


async def test_list_agents_deduplicates_multiple_bindings_per_agent(service, mock_repo):
    agent = make_agent()
    binding1 = AgentMCPServerDB(
        id=uuid4(),
        agent_id=agent.id,
        mcp_server_id=uuid4(),
        tools=None,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    binding2 = AgentMCPServerDB(
        id=uuid4(),
        agent_id=agent.id,
        mcp_server_id=uuid4(),
        tools=None,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    mock_repo.list_with_permissions.return_value = [
        (agent, binding1),
        (agent, binding2),
    ]

    result = await service.list(user_role=WorkspaceRole.admin)

    assert len(result) == 1
    assert len(result[0].mcp_servers) == 2


async def test_list_agents_owner_gets_owner_permission(service, mock_repo):
    owner_id = uuid4()
    agent = make_agent(owner_id=owner_id)
    mock_repo.list_with_permissions.return_value = [(agent, None, None)]

    result = await service.list(user_id=owner_id, user_role=WorkspaceRole.member)

    assert result[0].current_user_permission == "owner"


async def test_list_agents_admin_gets_admin_permission(service, mock_repo):
    agent = make_agent()
    mock_repo.list_with_permissions.return_value = [(agent, None)]

    result = await service.list(user_role=WorkspaceRole.admin)

    assert result[0].current_user_permission == "admin"


async def test_list_agents_granted_permission_from_row(service, mock_repo):
    agent = make_agent()
    non_owner_id = uuid4()
    mock_repo.list_with_permissions.return_value = [
        (agent, None, PermissionLevel.editor)
    ]

    result = await service.list(user_id=non_owner_id, user_role=WorkspaceRole.member)

    assert result[0].current_user_permission == "editor"


async def test_list_agents_no_permission_when_not_granted(service, mock_repo):
    agent = make_agent()
    non_owner_id = uuid4()
    mock_repo.list_with_permissions.return_value = [(agent, None, None)]

    result = await service.list(user_id=non_owner_id, user_role=WorkspaceRole.member)

    assert result[0].current_user_permission is None


async def test_list_agents_no_user_returns_agents_with_no_permission(
    service, mock_repo
):
    agent = make_agent()
    mock_repo.list_with_permissions.return_value = [(agent, None)]

    result = await service.list()

    assert result[0].current_user_permission is None


async def test_list_attaches_tag(service, mock_repo, mock_tag_service):
    tag_id = uuid4()
    agent = make_agent(tag_id=tag_id)
    mock_repo.list_with_permissions.return_value = [(agent, None)]
    mock_tag_service.list_by_ids.return_value = [
        TagDB(
            id=tag_id,
            name="Data",
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
    ]

    result = await service.list()

    mock_tag_service.list_by_ids.assert_awaited_once_with([tag_id])
    assert result[0].tag is not None
    assert result[0].tag.id == tag_id
    assert result[0].tag.name == "Data"


async def test_list_untagged_agents_attach_no_tag(service, mock_repo, mock_tag_service):
    agent = make_agent()
    mock_repo.list_with_permissions.return_value = [(agent, None)]

    result = await service.list()

    mock_tag_service.list_by_ids.assert_awaited_once_with([])
    assert result[0].tag is None


# ---------------------------------------------------------------------------
# update_agent
# ---------------------------------------------------------------------------


async def test_update_agent_delegates_to_repository(service, mock_repo):
    agent = make_agent()
    mock_repo.get.return_value = agent
    mock_repo.list_with_permissions.return_value = [(agent, None)]

    result = await service.update(
        agent.id, AgentPatch(name="Updated"), user_id=agent.owner_id
    )

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

    await service.update(agent.id, AgentPatch(name="New Name"), user_id=agent.owner_id)

    update_schema = mock_repo.update.call_args[0][1]
    assert isinstance(update_schema, AgentPatch)
    assert update_schema.model_dump(exclude_unset=True) == {"name": "New Name"}


async def test_update_agent_raises_404_when_not_found(service, mock_repo):
    mock_repo.list_with_permissions.return_value = []

    with pytest.raises(NotFoundError) as exc_info:
        await service.update(uuid4(), AgentPatch(name="X"))

    assert exc_info.value.detail == "Agent not found"
    mock_repo.update.assert_not_called()


async def test_update_agent_raises_403_when_no_permission(service, mock_repo):
    agent = make_agent()
    mock_repo.list_with_permissions.return_value = [(agent, None)]

    with pytest.raises(PermissionDeniedError):
        await service.update(agent.id, AgentPatch(name="X"), user_id=uuid4())

    mock_repo.get.assert_not_called()
    mock_repo.update.assert_not_called()


async def test_update_agent_allows_workspace_admin(service, mock_repo):
    agent = make_agent()
    mock_repo.get.return_value = agent
    mock_repo.list_with_permissions.return_value = [(agent, None)]

    await service.update(
        agent.id,
        AgentPatch(name="Renamed"),
        user_id=uuid4(),
        user_role=WorkspaceRole.admin,
    )

    mock_repo.update.assert_awaited_once()


async def test_update_agent_validates_tag_exists(service, mock_repo, mock_tag_service):
    agent = make_agent()
    mock_repo.get.return_value = agent
    mock_repo.list_with_permissions.return_value = [(agent, None)]
    tag_id = uuid4()

    await service.update(agent.id, AgentPatch(tag_id=tag_id), user_id=agent.owner_id)

    mock_tag_service.get.assert_awaited_once_with(tag_id)
    mock_repo.update.assert_awaited_once()


async def test_update_agent_raises_404_for_unknown_tag(
    service, mock_repo, mock_tag_service
):
    agent = make_agent()
    mock_repo.list_with_permissions.return_value = [(agent, None)]
    mock_tag_service.get.side_effect = NotFoundError("Tag not found")

    with pytest.raises(NotFoundError) as exc_info:
        await service.update(
            agent.id, AgentPatch(tag_id=uuid4()), user_id=agent.owner_id
        )

    assert exc_info.value.detail == "Tag not found"
    mock_repo.update.assert_not_called()


async def test_update_agent_untag_skips_tag_lookup(
    service, mock_repo, mock_tag_service
):
    agent = make_agent()
    mock_repo.get.return_value = agent
    mock_repo.list_with_permissions.return_value = [(agent, None)]

    await service.update(agent.id, AgentPatch(tag_id=None), user_id=agent.owner_id)

    mock_tag_service.get.assert_not_called()
    update_schema = mock_repo.update.call_args[0][1]
    assert update_schema.model_dump(exclude_unset=True) == {"tag_id": None}


# ---------------------------------------------------------------------------
# set_config
# ---------------------------------------------------------------------------


def make_config(**kwargs):
    defaults = {"name": "Configured", "instructions": "Do things"}
    return AgentConfig(**{**defaults, **kwargs})


async def test_set_config_orchestrates_scalars_bindings_subagents(
    service, mock_repo, mock_mcp_server_service, mock_subagent_service
):
    agent = make_agent()
    mock_repo.get.return_value = agent
    mock_repo.list_with_permissions.return_value = [(agent, None)]
    server_id = uuid4()
    sub_id = uuid4()
    config = make_config(
        description="A description",
        mcp_servers=[
            AgentMCPServerConfig(
                mcp_server_id=server_id,
                tools={"search": ToolStatus.needs_approval},
            )
        ],
        subagent_ids=[sub_id],
    )

    result = await service.set_config(agent.id, config, user_id=agent.owner_id)

    patch_schema = mock_repo.update.call_args[0][1]
    assert isinstance(patch_schema, AgentPatch)
    assert patch_schema.name == "Configured"
    assert patch_schema.description == "A description"
    mock_mcp_server_service.set_for_agent.assert_awaited_once_with(
        agent.id, config.mcp_servers
    )
    mock_subagent_service.set_for_supervisor.assert_awaited_once_with(
        agent.id, [sub_id], user_role=None
    )
    assert isinstance(result, AgentResponse)


async def test_set_config_clears_unset_scalars(service, mock_repo):
    """Full replace: omitting description/emoji/color in the config clears
    them — every scalar field is explicitly written."""
    agent = make_agent(description="old", emoji="🤖")
    mock_repo.get.return_value = agent
    mock_repo.list_with_permissions.return_value = [(agent, None)]

    await service.set_config(agent.id, make_config(), user_id=agent.owner_id)

    patch_schema = mock_repo.update.call_args[0][1]
    dumped = patch_schema.model_dump(exclude_unset=True)
    assert dumped["description"] is None
    assert dumped["emoji"] is None
    assert dumped["color"] is None
    assert dumped["has_code_interpreter"] is False
    assert "tag_id" not in dumped  # tags are outside the config document


async def test_set_config_denies_member(service, mock_repo):
    agent = make_agent()
    mock_repo.list_with_permissions.return_value = [
        (agent, None, PermissionLevel.member)
    ]

    with pytest.raises(PermissionDeniedError):
        await service.set_config(agent.id, make_config(), user_id=uuid4())

    mock_repo.update.assert_not_called()


async def test_set_config_denies_without_permission(
    service, mock_repo, mock_mcp_server_service
):
    agent = make_agent()
    mock_repo.list_with_permissions.return_value = [(agent, None)]

    with pytest.raises(PermissionDeniedError):
        await service.set_config(agent.id, make_config(), user_id=uuid4())

    mock_mcp_server_service.set_for_agent.assert_not_called()


async def test_set_config_allows_agent_editor(service, mock_repo):
    agent = make_agent()
    mock_repo.get.return_value = agent
    mock_repo.list_with_permissions.return_value = [
        (agent, None, PermissionLevel.editor)
    ]

    await service.set_config(agent.id, make_config(), user_id=uuid4())

    mock_repo.update.assert_awaited_once()


async def test_set_config_allows_workspace_admin(service, mock_repo):
    agent = make_agent()
    mock_repo.get.return_value = agent
    mock_repo.list_with_permissions.return_value = [(agent, None)]

    await service.set_config(
        agent.id, make_config(), user_id=uuid4(), user_role=WorkspaceRole.admin
    )

    mock_repo.update.assert_awaited_once()


async def test_set_config_passes_role_to_subagent_gate(
    service, mock_repo, mock_subagent_service
):
    agent = make_agent()
    mock_repo.get.return_value = agent
    mock_repo.list_with_permissions.return_value = [(agent, None)]
    sub_id = uuid4()

    await service.set_config(
        agent.id,
        make_config(subagent_ids=[sub_id]),
        user_id=uuid4(),
        user_role=WorkspaceRole.admin,
    )

    mock_subagent_service.set_for_supervisor.assert_awaited_once_with(
        agent.id, [sub_id], user_role=WorkspaceRole.admin
    )


async def test_set_config_subagent_denial_propagates(
    service, mock_repo, mock_subagent_service
):
    """A PermissionDeniedError from the subagent gate bubbles up — the request
    transaction rolls back, so the scalar/MCP writes never commit."""
    agent = make_agent()
    mock_repo.get.return_value = agent
    mock_repo.list_with_permissions.return_value = [
        (agent, None, PermissionLevel.editor)
    ]
    mock_subagent_service.set_for_supervisor.side_effect = PermissionDeniedError(
        "Only admins can modify subagents"
    )

    with pytest.raises(PermissionDeniedError):
        await service.set_config(
            agent.id, make_config(subagent_ids=[uuid4()]), user_id=uuid4()
        )


def test_agent_config_rejects_duplicate_servers():
    server_id = uuid4()
    with pytest.raises(ValueError, match="duplicate"):
        AgentConfig(
            name="X",
            instructions="Y",
            mcp_servers=[
                AgentMCPServerConfig(mcp_server_id=server_id, tools=None),
                AgentMCPServerConfig(mcp_server_id=server_id, tools=None),
            ],
        )


def test_agent_config_rejects_invalid_color():
    with pytest.raises(ValueError, match="color"):
        AgentConfig(name="X", instructions="Y", color="#123456")


# ---------------------------------------------------------------------------
# delete_agent
# ---------------------------------------------------------------------------


async def test_delete_agent_delegates_to_repository(
    service, mock_repo, mock_subagent_service
):
    agent = make_agent()
    mock_repo.get.return_value = agent

    await service.delete(agent.id, user_id=agent.owner_id)

    mock_repo.get.assert_awaited_once_with(agent.id)
    mock_subagent_service.delete_all_for_agent.assert_awaited_once_with(agent.id)
    mock_repo.archive.assert_awaited_once_with(agent)


async def test_delete_agent_raises_404_when_not_found(service, mock_repo):
    mock_repo.get.return_value = None

    with pytest.raises(NotFoundError) as exc_info:
        await service.delete(uuid4())

    assert exc_info.value.detail == "Agent not found"
    mock_repo.archive.assert_not_called()


async def test_delete_agent_raises_403_for_non_owner(
    service, mock_repo, mock_subagent_service
):
    agent = make_agent()
    mock_repo.get.return_value = agent

    with pytest.raises(PermissionDeniedError):
        await service.delete(agent.id, user_id=uuid4())

    mock_subagent_service.delete_all_for_agent.assert_not_called()
    mock_repo.archive.assert_not_called()


async def test_delete_agent_allows_workspace_admin(
    service, mock_repo, mock_subagent_service
):
    agent = make_agent()
    mock_repo.get.return_value = agent

    await service.delete(agent.id, user_id=uuid4(), user_role=WorkspaceRole.admin)

    mock_subagent_service.delete_all_for_agent.assert_awaited_once_with(agent.id)
    mock_repo.archive.assert_awaited_once_with(agent)


# ---------------------------------------------------------------------------
# restore
# ---------------------------------------------------------------------------


async def test_restore_agent_sets_unarchived_for_owner(service, mock_repo):
    agent = make_agent(is_archived=True)
    mock_repo.get.return_value = agent
    mock_repo.list_with_permissions.return_value = [(agent, None)]

    await service.restore(agent.id, user_id=agent.owner_id)

    mock_repo.restore.assert_awaited_once_with(agent)


async def test_restore_agent_allows_workspace_admin(service, mock_repo):
    agent = make_agent(is_archived=True)
    mock_repo.get.return_value = agent
    mock_repo.list_with_permissions.return_value = [(agent, None)]

    await service.restore(agent.id, user_id=uuid4(), user_role=WorkspaceRole.admin)

    mock_repo.restore.assert_awaited_once_with(agent)


async def test_restore_agent_denied_for_editor(service, mock_repo):
    agent = make_agent(is_archived=True)
    mock_repo.list_with_permissions.return_value = [
        (agent, None, PermissionLevel.editor)
    ]

    with pytest.raises(PermissionDeniedError):
        await service.restore(agent.id, user_id=uuid4())

    mock_repo.restore.assert_not_called()


# ---------------------------------------------------------------------------
# delete_permanently
# ---------------------------------------------------------------------------


async def test_delete_permanently_cascades_for_owner(
    service,
    mock_repo,
    mock_subagent_service,
    mock_thread_service,
    mock_agent_mcp_repo,
):
    agent = make_agent(is_archived=True)
    mock_repo.get.return_value = agent
    mock_repo.list_with_permissions.return_value = [(agent, None)]

    await service.delete_permanently(agent.id, user_id=agent.owner_id)

    mock_subagent_service.delete_all_for_agent.assert_awaited_once_with(agent.id)
    mock_agent_mcp_repo.delete_all_for_agent.assert_awaited_once_with(agent.id)
    mock_thread_service.delete_rows_for_agent.assert_awaited_once_with(agent.id)
    mock_repo.delete_all_permissions.assert_awaited_once_with(agent.id)
    mock_repo.delete.assert_awaited_once_with(agent)
    # Checkpoints are purged last, after every DB delete has run.
    mock_thread_service.purge_checkpoints.assert_awaited_once_with(["t1", "t2"])


async def test_delete_permanently_purges_checkpoints_after_db_deletes(
    service, mock_repo, mock_thread_service
):
    """Checkpoint purge (non-rollbackable) must run after the agent row delete."""
    agent = make_agent(is_archived=True)
    mock_repo.get.return_value = agent
    mock_repo.list_with_permissions.return_value = [(agent, None)]

    manager = MagicMock()
    manager.attach_mock(mock_repo.delete, "delete_agent")
    manager.attach_mock(mock_thread_service.purge_checkpoints, "purge_checkpoints")

    await service.delete_permanently(agent.id, user_id=agent.owner_id)

    ordered = [name for name, _, _ in manager.mock_calls]
    assert ordered.index("delete_agent") < ordered.index("purge_checkpoints")


async def test_delete_permanently_denied_for_editor(
    service, mock_repo, mock_agent_mcp_repo
):
    agent = make_agent(is_archived=True)
    mock_repo.list_with_permissions.return_value = [
        (agent, None, PermissionLevel.editor)
    ]

    with pytest.raises(PermissionDeniedError):
        await service.delete_permanently(agent.id, user_id=uuid4())

    mock_agent_mcp_repo.delete_all_for_agent.assert_not_called()
    mock_repo.delete.assert_not_called()


# ---------------------------------------------------------------------------
# check_ready
# ---------------------------------------------------------------------------


async def test_check_ready_returns_ready_when_no_mcp_servers(service, mock_repo):
    agent = make_agent()
    mock_repo.list_with_permissions.return_value = [(agent, None)]

    result = await service.describe_readiness(agent.id, "user-id")

    assert result["ready"] is True
    assert result["status"] == "ready"
    assert result["disconnected_servers"] == []


async def test_check_ready_returns_not_configured_when_tools_is_none(
    service, mock_repo
):
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

    result = await service.describe_readiness(agent.id, "user-id")

    assert result["ready"] is False
    assert result["status"] == "not_configured"


async def test_check_ready_returns_ready_when_all_servers_connected(
    service, mock_db, mock_repo
):
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
        "app.agents.core.service.is_authorized",
        new=AsyncMock(return_value=True),
    ):
        result = await service.describe_readiness(agent.id, "user-id")

    assert result["ready"] is True
    assert result["disconnected_servers"] == []


async def test_check_ready_returns_not_ready_when_server_disconnected(
    service, mock_db, mock_repo
):
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
        "app.agents.core.service.is_authorized",
        new=AsyncMock(return_value=False),
    ):
        result = await service.describe_readiness(agent.id, "user-id")

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
        "app.agents.core.service.is_authorized",
        new=AsyncMock(return_value=False),
    ):
        result = await service.describe_readiness(agent.id, "user-id")

    assert result["status"] == "disconnected"


def _readiness_resp(mcp_server_ids, *, subagent_ids=(), tools_ok=True):
    """Duck-typed AgentResponse for readiness/enumeration tests."""
    resp = MagicMock()
    resp.mcp_servers = [
        MagicMock(
            mcp_server_id=sid,
            tools=({"x": ToolStatus.always_allow} if tools_ok else None),
        )
        for sid in mcp_server_ids
    ]
    resp.subagents = [MagicMock(id=sub) for sub in subagent_ids]
    return resp


async def test_describe_readiness_includes_subagent_servers(service, mock_db):
    # The bug: a subagent's unauthorized OAuth server must keep the agent "not
    # ready" — otherwise the run launches and fails mid-flight.
    parent_id, sub_id = uuid4(), uuid4()
    parent_server, sub_server = uuid4(), uuid4()
    responses = {
        parent_id: _readiness_resp([parent_server], subagent_ids=[sub_id]),
        sub_id: _readiness_resp([sub_server]),
    }
    service.get = AsyncMock(side_effect=lambda aid, **_: responses[aid])
    mock_db.execute.return_value = _make_mock_execute_result(
        scalars_list=[MagicMock(id=parent_server), MagicMock(id=sub_server)]
    )

    with patch(
        "app.agents.core.service.is_authorized",
        # parent authorized, subagent's server is not
        new=AsyncMock(side_effect=lambda s, _u: s.id == parent_server),
    ):
        result = await service.describe_readiness(parent_id, "user-id")

    assert result["ready"] is False
    assert str(sub_server) in result["disconnected_servers"]
    assert str(parent_server) not in result["disconnected_servers"]


async def test_collect_run_bindings_keeps_shared_server_across_agents(service):
    # `tools` is per binding, so a server shared by parent + subagent yields
    # BOTH bindings (not deduped) — the readiness check needs to see each one.
    parent_id, sub_id = uuid4(), uuid4()
    shared = uuid4()
    responses = {
        parent_id: _readiness_resp([shared], subagent_ids=[sub_id]),
        sub_id: _readiness_resp([shared]),
    }
    service.get = AsyncMock(side_effect=lambda aid, **_: responses[aid])

    bindings = await service.collect_run_bindings(parent_id)

    assert [b.mcp_server_id for b in bindings] == [shared, shared]


async def test_describe_readiness_flags_unconfigured_shared_subagent_binding(service):
    # Parent configures server X; a subagent binds the SAME X but leaves it
    # unconfigured (tools=None). Deduping by server id would hide the None and
    # wrongly report ready — it must be not_configured.
    parent_id, sub_id = uuid4(), uuid4()
    shared = uuid4()
    responses = {
        parent_id: _readiness_resp([shared], subagent_ids=[sub_id], tools_ok=True),
        sub_id: _readiness_resp([shared], tools_ok=False),
    }
    service.get = AsyncMock(side_effect=lambda aid, **_: responses[aid])

    result = await service.describe_readiness(parent_id, "user-id")

    assert result["ready"] is False
    assert result["status"] == "not_configured"


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


def test_resolve_permission_returns_member_when_team_granted(service):
    agent = make_agent()

    result = service._resolve_permission(
        agent, uuid4(), WorkspaceRole.member, {}, {agent.id}
    )

    assert result == "member"


def test_resolve_permission_explicit_grant_beats_team(service):
    agent = make_agent()
    granted = {agent.id: "editor"}

    result = service._resolve_permission(
        agent, uuid4(), WorkspaceRole.member, granted, {agent.id}
    )

    assert result == "editor"


def test_resolve_permission_no_team_grant_when_agent_not_in_set(service):
    agent = make_agent()

    result = service._resolve_permission(
        agent, uuid4(), WorkspaceRole.member, {}, {uuid4()}
    )

    assert result is None


# ---------------------------------------------------------------------------
# team grants through list (4-tuple rows carry the team match)
# ---------------------------------------------------------------------------


async def test_list_agents_team_member_gets_member(service, mock_repo):
    agent = make_agent()
    team_id = uuid4()
    # 4th element = matching agent↔team link's team_id
    mock_repo.list_with_permissions.return_value = [(agent, None, None, team_id)]

    result = await service.list(
        user_id=uuid4(), user_role=WorkspaceRole.member, user_team_id=team_id
    )

    assert result[0].current_user_permission == "member"


async def test_list_agents_explicit_editor_beats_team(service, mock_repo):
    agent = make_agent()
    team_id = uuid4()
    mock_repo.list_with_permissions.return_value = [
        (agent, None, PermissionLevel.editor, team_id)
    ]

    result = await service.list(
        user_id=uuid4(), user_role=WorkspaceRole.member, user_team_id=team_id
    )

    assert result[0].current_user_permission == "editor"


async def test_list_agents_no_team_match_stays_none(service, mock_repo):
    agent = make_agent()
    mock_repo.list_with_permissions.return_value = [(agent, None, None, None)]

    result = await service.list(
        user_id=uuid4(), user_role=WorkspaceRole.member, user_team_id=uuid4()
    )

    assert result[0].current_user_permission is None


# ---------------------------------------------------------------------------
# agent team bindings
# ---------------------------------------------------------------------------


async def test_get_team_ids_delegates(service, mock_repo):
    agent_id = uuid4()
    team_ids = [uuid4(), uuid4()]
    mock_repo.get_team_ids = AsyncMock(return_value=team_ids)

    result = await service.get_team_ids(agent_id)

    mock_repo.get_team_ids.assert_awaited_once_with(agent_id)
    assert result == team_ids


async def test_set_teams_delegates(service, mock_repo):
    agent_id = uuid4()
    team_ids = [uuid4()]
    mock_repo.set_teams = AsyncMock(return_value=team_ids)

    result = await service.set_teams(agent_id, team_ids)

    mock_repo.set_teams.assert_awaited_once_with(agent_id, team_ids)
    assert result == team_ids


async def test_delete_permanently_cleans_team_links(
    service, mock_repo, mock_subagent_service
):
    agent = make_agent(is_archived=True)
    mock_repo.get.return_value = agent
    mock_repo.list_with_permissions.return_value = [(agent, None)]
    mock_repo.delete_all_teams = AsyncMock()

    await service.delete_permanently(agent.id, user_id=agent.owner_id)

    mock_repo.delete_all_teams.assert_awaited_once_with(agent.id)
