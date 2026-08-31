from contextlib import contextmanager
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.agents.core.service import get_agent_service
from app.agents.mcp_servers.service import get_agent_mcp_server_service
from app.agents.models import AgentDB, EffectivePermission
from app.exceptions import NotFoundError, PermissionDeniedError
from app.main import app
from app.threads.models import ThreadDB, ThreadSource
from app.threads.service import get_thread_service


@pytest.fixture(autouse=True)
def _no_sandbox_bindings():
    """These tests drive db.execute with one shared mock result; the sandbox
    hydration query would otherwise consume it. No test here binds one."""
    with patch(
        "app.agents.core.service.AgentSandboxRepository.list_for_agents",
        new=AsyncMock(return_value=[]),
    ):
        yield


def make_result(*, scalar=None, rows=None, scalars_list=None, access=None):
    """One canned `db.execute` result.

    `access` is the row the permission gate reads
    (`AgentRepository.get_access`): `(owner_id, granted_permission | None)`, or
    `None` for an agent the caller cannot see. Every gated endpoint issues that
    query first, so a side_effect list starts with one.
    """
    r = MagicMock()
    r.scalar_one_or_none.return_value = scalar
    r.all.return_value = rows or []
    r.first.return_value = access
    r.scalars.return_value.all.return_value = scalars_list or []
    return r


def owner_access(agent):
    return make_result(access=(agent.owner_id, None))


def test_create_agent(client: TestClient, mock_db, editor_user):
    """Test creating a new agent (editor or above) from a config document."""
    agent_data = {
        "name": "Test Agent",
        "instructions": "You are a helpful assistant.",
    }

    created: dict = {}

    # Mock refresh to populate the created agent with generated fields
    async def mock_refresh(obj):
        obj.id = uuid4()
        obj.created_at = datetime.now()
        obj.updated_at = datetime.now()
        created["agent"] = obj

    mock_db.refresh = mock_refresh

    # One result shape serves every post-create query: the binding/subagent
    # lookups consume .scalars().all() (empty), the final get consumes .all()
    # (the created agent row).
    def execute_side_effect(*_args, **_kwargs):
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        result.all.return_value = (
            [(created["agent"], None, None)] if "agent" in created else []
        )
        return result

    mock_db.execute.side_effect = execute_side_effect

    response = client.post("/agents/", json=agent_data)

    assert response.status_code == 201
    data = response.json()
    assert data["name"] == agent_data["name"]
    assert data["instructions"] == agent_data["instructions"]
    assert data["owner_id"] == str(editor_user.id)
    assert "id" in data
    assert "created_at" in data
    assert "updated_at" in data


def test_get_agents(client: TestClient, mock_db, current_user):
    """Test getting all agents."""
    owner_id = current_user.id
    agent1 = AgentDB(
        id=uuid4(),
        name="Agent 1",
        instructions="First agent",
        owner_id=owner_id,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    agent2 = AgentDB(
        id=uuid4(),
        name="Agent 2",
        instructions="Second agent",
        owner_id=owner_id,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    mock_result = MagicMock()
    mock_result.all.return_value = [(agent1, None, None), (agent2, None, None)]
    mock_db.execute.return_value = mock_result

    response = client.get("/agents/")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2


def test_get_agents_filter_by_owner(client: TestClient, mock_db, current_user):
    """Test getting agents filtered by owner_id."""
    owner_id = current_user.id
    agent = AgentDB(
        id=uuid4(),
        name="Agent 1",
        instructions="Agent for user 1",
        owner_id=owner_id,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    mock_result = MagicMock()
    mock_result.all.return_value = [(agent, None, None)]
    mock_db.execute.return_value = mock_result

    response = client.get(f"/agents/?owner_id={owner_id}")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["name"] == agent.name


def test_get_agent(client: TestClient, mock_db, current_user):
    """Test getting a single agent by ID."""
    agent_id = uuid4()
    owner_id = current_user.id
    agent = AgentDB(
        id=agent_id,
        name="Test Agent",
        instructions="Test instructions",
        owner_id=owner_id,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    mock_result = MagicMock()
    mock_result.all.return_value = [(agent, None)]
    mock_db.execute.return_value = mock_result

    response = client.get(f"/agents/{agent_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(agent_id)
    assert data["name"] == agent.name


@pytest.mark.usefixtures("current_user")
def test_get_agent_not_found(client: TestClient, mock_db):
    """Test getting a non-existent agent returns 404."""
    fake_id = uuid4()

    mock_result = MagicMock()
    mock_result.all.return_value = []
    mock_db.execute.return_value = mock_result

    response = client.get(f"/agents/{fake_id}")
    assert response.status_code == 404
    assert response.json()["detail"] == "Agent not found"


def test_get_agent_requires_auth(client: TestClient):
    """Test that GET /agents/{id} returns 401 without auth."""
    response = client.get(f"/agents/{uuid4()}")
    assert response.status_code == 401


def test_update_agent(client: TestClient, mock_db, current_user):
    """Test updating an agent (owner)."""
    agent_id = uuid4()
    owner_id = current_user.id
    agent = AgentDB(
        id=agent_id,
        name="Updated Agent",
        instructions="Updated instructions",
        owner_id=owner_id,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    # get_tags_by_ids short-circuits when no agent has a tag_id, so the
    # untagged agents here consume no extra execute result.
    mock_db.execute.side_effect = [
        owner_access(agent),  # require_permission: get_access
        make_result(scalar=agent),  # get_or_404: repository.get
        make_result(rows=[(agent, None)]),  # get_agent (return): list_with_permissions
        make_result(scalars_list=[]),  # get_agent (return): list_all_subagent_data
        make_result(scalars_list=[]),  # get_agent (return): owner list_by_ids
    ]

    update_data = {
        "name": "Updated Agent",
        "instructions": "Updated instructions",
    }

    response = client.patch(f"/agents/{agent_id}", json=update_data)
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(agent_id)
    assert data["name"] == update_data["name"]
    assert data["instructions"] == update_data["instructions"]
    assert data["mcp_servers"] == []


@pytest.mark.usefixtures("current_user")
def test_update_agent_not_found(client: TestClient, mock_db):
    """Test updating a non-existent agent returns 404."""
    fake_id = uuid4()

    mock_db.execute.return_value = make_result(access=None)

    update_data = {"name": "Updated Name"}
    response = client.patch(f"/agents/{fake_id}", json=update_data)
    assert response.status_code == 404
    assert response.json()["detail"] == "Agent not found"


def test_update_agent_forbidden_for_non_owner(
    client: TestClient, mock_db, current_user
):
    """A member who is neither owner nor admin cannot update an agent."""
    agent_id = uuid4()
    other_owner = uuid4()
    assert other_owner != current_user.id
    agent = AgentDB(
        id=agent_id,
        name="Someone Else's Agent",
        instructions="...",
        owner_id=other_owner,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    # get_access: the agent exists, this user has no grant on it
    mock_db.execute.return_value = make_result(access=(agent.owner_id, None))

    response = client.patch(f"/agents/{agent_id}", json={"name": "Pwned"})
    assert response.status_code == 403


def test_delete_agent(client: TestClient, mock_db, current_user):
    """Owner can delete their own agent."""
    agent_id = uuid4()
    agent = AgentDB(
        id=agent_id,
        name="Agent to Delete",
        instructions="This agent will be deleted",
        owner_id=current_user.id,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    mock_db.execute.return_value = make_result(
        scalar=agent, access=(agent.owner_id, None)
    )

    response = client.delete(f"/agents/{agent_id}")
    assert response.status_code == 204


@pytest.mark.usefixtures("current_user")
def test_delete_agent_not_found(client: TestClient, mock_db):
    """Test deleting a non-existent agent returns 404."""
    fake_id = uuid4()

    mock_db.execute.return_value = make_result(scalar=None, access=None)

    response = client.delete(f"/agents/{fake_id}")
    assert response.status_code == 404
    assert response.json()["detail"] == "Agent not found"


def test_delete_agent_forbidden_for_non_owner(
    client: TestClient, mock_db, current_user
):
    """A member who is neither owner nor admin cannot delete an agent."""
    other_owner = uuid4()
    assert other_owner != current_user.id
    agent = AgentDB(
        id=uuid4(),
        name="Someone Else's Agent",
        instructions="...",
        owner_id=other_owner,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    mock_db.execute.return_value = make_result(
        scalar=agent, access=(agent.owner_id, None)
    )

    response = client.delete(f"/agents/{agent.id}")
    assert response.status_code == 403
    assert agent.is_archived is False


def test_delete_agent_allows_workspace_admin(client: TestClient, mock_db, admin_user):
    """Workspace admin can delete any agent."""
    other_owner = uuid4()
    assert other_owner != admin_user.id
    agent = AgentDB(
        id=uuid4(),
        name="Other User's Agent",
        instructions="...",
        owner_id=other_owner,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    mock_db.execute.return_value = make_result(
        scalar=agent, access=(agent.owner_id, None)
    )

    response = client.delete(f"/agents/{agent.id}")
    assert response.status_code == 204


def test_delete_agent_requires_auth(client: TestClient):
    """Test that DELETE /agents/{id} returns 401 without auth."""
    response = client.delete(f"/agents/{uuid4()}")
    assert response.status_code == 401


def test_get_agents_archived_passthrough(client: TestClient, mock_db, current_user):
    """GET /agents?archived=true returns the archived list."""
    agent = AgentDB(
        id=uuid4(),
        name="Archived Agent",
        instructions="...",
        owner_id=current_user.id,
        is_archived=True,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    mock_result = MagicMock()
    mock_result.all.return_value = [(agent, None, None)]
    mock_db.execute.return_value = mock_result

    response = client.get("/agents/?archived=true")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["is_archived"] is True


def test_restore_agent_as_owner(client: TestClient, mock_db, current_user):
    """Owner can restore an archived agent."""
    agent = AgentDB(
        id=uuid4(),
        name="Archived Agent",
        instructions="...",
        owner_id=current_user.id,
        is_archived=True,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    mock_db.execute.return_value = make_result(
        rows=[(agent, None)], scalar=agent, access=(agent.owner_id, None)
    )

    response = client.post(f"/agents/{agent.id}/restore")
    assert response.status_code == 200


def test_restore_agent_requires_auth(client: TestClient):
    response = client.post(f"/agents/{uuid4()}/restore")
    assert response.status_code == 401


def test_delete_agent_permanently_requires_auth(client: TestClient):
    response = client.delete(f"/agents/{uuid4()}/permanent")
    assert response.status_code == 401


def test_delete_agent_permanently_forbidden_for_non_manager(
    client: TestClient, mock_db, current_user
):
    """A user without owner/admin permission cannot permanently delete."""
    other_owner = uuid4()
    assert other_owner != current_user.id
    agent = AgentDB(
        id=uuid4(),
        name="Someone Else's Agent",
        instructions="...",
        owner_id=other_owner,
        is_archived=True,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    mock_db.execute.return_value = make_result(access=(agent.owner_id, None))

    response = client.delete(f"/agents/{agent.id}/permanent")
    assert response.status_code == 403


def test_delete_permanently_commits_before_purging_checkpoints(
    client: TestClient, mock_db, current_user
):
    """Checkpoints live on a separate auto-committed connection and cannot be
    rolled back, so they must be purged only once the row deletes are committed
    — not merely flushed. Purging first meant a failed commit left an agent
    whose entire history was irrecoverably gone (P1-9's residual, §5.5)."""
    agent = AgentDB(
        id=uuid4(),
        name="Doomed",
        instructions="...",
        owner_id=current_user.id,
        is_archived=True,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    mock_db.execute.return_value = make_result(
        access=(agent.owner_id, None), scalars_list=["t1"]
    )

    calls = MagicMock()
    calls.attach_mock(mock_db.commit, "commit")
    with patch("app.threads.service.get_checkpointer") as checkpointer:
        checkpointer.return_value.__aenter__.return_value = MagicMock(
            adelete_thread=AsyncMock()
        )
        calls.attach_mock(
            checkpointer.return_value.__aenter__.return_value.adelete_thread, "purge"
        )
        response = client.delete(f"/agents/{agent.id}/permanent")

    assert response.status_code == 204
    ordered = [name for name, _, _ in calls.mock_calls]
    assert "commit" in ordered and "purge" in ordered
    assert ordered.index("commit") < ordered.index("purge")


def test_delete_permanently_still_succeeds_when_the_purge_fails(
    client: TestClient, mock_db, current_user
):
    """Past the commit the agent really is gone, so a purge failure must not
    become a 500 the client would retry into a 404. The orphaned checkpoints are
    logged instead."""
    agent = AgentDB(
        id=uuid4(),
        name="Doomed",
        instructions="...",
        owner_id=current_user.id,
        is_archived=True,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    mock_db.execute.return_value = make_result(
        access=(agent.owner_id, None), scalars_list=["t1"]
    )

    with patch("app.threads.service.get_checkpointer") as checkpointer:
        checkpointer.return_value.__aenter__.side_effect = RuntimeError("redis gone")
        response = client.delete(f"/agents/{agent.id}/permanent")

    assert response.status_code == 204
    mock_db.commit.assert_awaited()


def make_count_result(total: int) -> MagicMock:
    """Result of the count query BaseRepository.paginate runs before the page."""
    r = MagicMock()
    r.scalar_one.return_value = total
    return r


def _make_thread(*, agent_id, user_id, source=ThreadSource.web) -> ThreadDB:
    return ThreadDB(
        id=str(uuid4()),
        agent_id=agent_id,
        user_id=user_id,
        first_message_content="hi",
        source=source,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )


def test_list_agent_threads_as_owner(client: TestClient, mock_db, current_user):
    """An agent owner can list every thread for that agent."""
    agent_id = uuid4()
    agent = AgentDB(
        id=agent_id,
        name="Owned Agent",
        instructions="...",
        owner_id=current_user.id,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    thread = _make_thread(
        agent_id=agent_id,
        user_id=uuid4(),
        source=ThreadSource.slack,
    )

    mock_db.execute.side_effect = [
        # the route's gate: get_access, resolving current_user as the owner
        owner_access(agent),
        # ThreadRepository.list_for_agent: paginate count
        make_count_result(1),
        # ThreadRepository.list_for_agent: page rows
        make_result(
            rows=[
                (
                    thread,
                    "Owned Agent",
                    None,
                    None,
                    False,
                    "viewer@test.com",
                    "Viewer Name",
                )
            ]
        ),
    ]

    response = client.get(f"/agents/{agent_id}/threads")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert len(data["items"]) == 1
    assert data["items"][0]["user_email"] == "viewer@test.com"
    assert data["items"][0]["source"] == ThreadSource.slack.value


def test_list_agent_threads_forbidden_for_member(
    client: TestClient, mock_db, current_user
):
    """A workspace member with no agent permission gets a 403."""
    agent_id = uuid4()
    other_owner = uuid4()
    assert other_owner != current_user.id
    agent = AgentDB(
        id=agent_id,
        name="Other agent",
        instructions="...",
        owner_id=other_owner,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    # get_access: the agent exists, this user has no grant on it
    mock_db.execute.return_value = make_result(access=(agent.owner_id, None))

    response = client.get(f"/agents/{agent_id}/threads")
    assert response.status_code == 403


@pytest.mark.usefixtures("admin_user")
def test_list_agent_threads_as_workspace_admin(client: TestClient, mock_db):
    """Workspace admins see threads on any agent."""
    agent_id = uuid4()
    other_owner = uuid4()
    agent = AgentDB(
        id=agent_id,
        name="Some agent",
        instructions="...",
        owner_id=other_owner,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    thread = _make_thread(agent_id=agent_id, user_id=other_owner)

    mock_db.execute.side_effect = [
        owner_access(agent),  # the route's gate: get_access (admin role wins)
        make_count_result(1),  # list_for_agent: paginate count
        make_result(
            rows=[
                (
                    thread,
                    "Some agent",
                    None,
                    None,
                    False,
                    "creator@test.com",
                    "Creator",
                )
            ]
        ),
    ]

    response = client.get(f"/agents/{agent_id}/threads")
    assert response.status_code == 200
    assert len(response.json()["items"]) == 1


def test_list_agent_threads_requires_auth(client: TestClient):
    response = client.get(f"/agents/{uuid4()}/threads")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# agent team bindings — authorization
# ---------------------------------------------------------------------------


def _service_stub(permission):
    """A stand-in `AgentService` whose gate answers as if the caller held
    `permission` on the agent. The resolution itself is tested against a real
    database in `test_access.py`; what these tests pin is which level each
    route demands.
    """
    svc = MagicMock()

    async def _require(_agent_id, *, at_least, action, **_kwargs):
        if permission is None or not permission.covers(at_least):
            raise PermissionDeniedError(f"Not authorized to {action}")
        return permission

    svc.require_permission = AsyncMock(side_effect=_require)
    return svc


@contextmanager
def _as(permission, service_dependency=None, service=None):
    """Run the block with the agent gate resolving to `permission`.

    `service_dependency` lets a route whose *handler* uses another service
    (the MCP-binding routes) keep its own stub while the gate uses ours.
    """
    gate = _service_stub(permission)
    app.dependency_overrides[get_agent_service] = lambda: gate
    if service_dependency is not None:
        app.dependency_overrides[service_dependency] = lambda: service
    try:
        yield gate
    finally:
        app.dependency_overrides.pop(get_agent_service, None)
        if service_dependency is not None:
            app.dependency_overrides.pop(service_dependency, None)


@pytest.mark.usefixtures("current_user")
def test_set_agent_teams_forbidden_for_non_editor(client: TestClient):
    with _as(None) as gate:
        gate.set_teams = AsyncMock()
        response = client.put(f"/agents/{uuid4()}/teams", json={"team_ids": []})

    assert response.status_code == 403
    gate.set_teams.assert_not_called()


@pytest.mark.usefixtures("current_user")
def test_set_agent_teams_allows_editor(client: TestClient):
    with _as(EffectivePermission.editor) as gate:
        gate.set_teams = AsyncMock(return_value=[])
        response = client.put(f"/agents/{uuid4()}/teams", json={"team_ids": []})

    assert response.status_code == 200
    gate.set_teams.assert_awaited_once()


@pytest.mark.usefixtures("current_user")
def test_get_agent_teams_forbidden_for_non_editor(client: TestClient):
    with _as(None) as gate:
        gate.get_team_ids = AsyncMock(return_value=[])
        response = client.get(f"/agents/{uuid4()}/teams")

    assert response.status_code == 403
    gate.get_team_ids.assert_not_called()


# ---------------------------------------------------------------------------
# the gate each route demands (design review §4.4: several were login-only)
# ---------------------------------------------------------------------------


def _call(client: TestClient, method: str, path: str):
    agent_id, server_id = uuid4(), uuid4()
    url = path.format(agent_id=agent_id, server_id=server_id)
    # An empty body is enough: the gate runs before the handler, so a request
    # that gets past it fails validation (422) rather than authorization (403).
    if method in ("post", "put", "patch"):
        return getattr(client, method)(url, json={})
    return getattr(client, method)(url)


# (method, path, the weakest permission that may pass)
GATED_ROUTES = [
    ("get", "/agents/{agent_id}/permissions", EffectivePermission.admin),
    ("put", "/agents/{agent_id}/permissions", EffectivePermission.admin),
    ("get", "/agents/{agent_id}/teams", EffectivePermission.editor),
    ("put", "/agents/{agent_id}/teams", EffectivePermission.editor),
    ("post", "/agents/{agent_id}/mcp-servers/{server_id}", EffectivePermission.editor),
    ("patch", "/agents/{agent_id}/mcp-servers/{server_id}", EffectivePermission.editor),
    (
        "delete",
        "/agents/{agent_id}/mcp-servers/{server_id}",
        EffectivePermission.editor,
    ),
    (
        "post",
        "/agents/{agent_id}/mcp-servers/{server_id}/sync-tools",
        EffectivePermission.editor,
    ),
    ("get", "/agents/{agent_id}/is-ready", EffectivePermission.member),
    ("get", "/agents/{agent_id}/threads", EffectivePermission.admin),
]


@pytest.mark.usefixtures("current_user")
@pytest.mark.parametrize(("method", "path", "at_least"), GATED_ROUTES)
def test_route_rejects_a_caller_with_no_access(client, method, path, at_least):
    with _as(None):
        assert _call(client, method, path).status_code == 403


@pytest.mark.usefixtures("current_user")
@pytest.mark.parametrize(("method", "path", "at_least"), GATED_ROUTES)
def test_route_rejects_the_level_just_below_it(client, method, path, at_least):
    """The interesting half: a member may poll is-ready but must not retype a
    tool map, and an editor may bind servers but must not read the grant list.
    """
    weaker = {
        EffectivePermission.editor: EffectivePermission.member,
        EffectivePermission.admin: EffectivePermission.editor,
    }.get(at_least)
    if weaker is None:  # member is the weakest level there is
        pytest.skip("no weaker permission exists")

    with _as(weaker):
        assert _call(client, method, path).status_code == 403


@pytest.mark.usefixtures("current_user")
@pytest.mark.parametrize(("method", "path", "at_least"), GATED_ROUTES)
def test_route_admits_the_level_it_asks_for(client, method, path, at_least):
    """Past the gate — the handler's own service is stubbed, so any 2xx/4xx
    other than 403 means the gate let the request through."""
    agent_service = _service_stub(at_least)
    mcp_service = MagicMock()
    mcp_service.create_or_update = AsyncMock(side_effect=NotFoundError("stub"))
    mcp_service.update = AsyncMock(side_effect=NotFoundError("stub"))
    mcp_service.delete = AsyncMock(side_effect=NotFoundError("stub"))
    mcp_service.sync_tools = AsyncMock(side_effect=NotFoundError("stub"))
    agent_service.get_permissions = AsyncMock(return_value=[])
    agent_service.set_permissions = AsyncMock(return_value=[])
    agent_service.get_team_ids = AsyncMock(return_value=[])
    agent_service.set_teams = AsyncMock(return_value=[])
    agent_service.describe_readiness = AsyncMock(return_value={"ready": True})
    thread_service = MagicMock()
    thread_service.list_for_agent = AsyncMock(side_effect=NotFoundError("stub"))

    app.dependency_overrides[get_agent_service] = lambda: agent_service
    app.dependency_overrides[get_agent_mcp_server_service] = lambda: mcp_service
    app.dependency_overrides[get_thread_service] = lambda: thread_service
    try:
        assert _call(client, method, path).status_code != 403
    finally:
        for dependency in (
            get_agent_service,
            get_agent_mcp_server_service,
            get_thread_service,
        ):
            app.dependency_overrides.pop(dependency, None)
