from datetime import datetime
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.agents.models import AgentDB
from app.threads.models import ThreadDB, ThreadSource


def test_create_agent(client: TestClient, mock_db, editor_user):
    """Test creating a new agent (editor or above)."""
    agent_data = {
        "name": "Test Agent",
        "instructions": "You are a helpful assistant.",
    }

    # Mock refresh to populate the created agent with generated fields
    async def mock_refresh(obj):
        obj.id = uuid4()
        obj.created_at = datetime.now()
        obj.updated_at = datetime.now()

    mock_db.refresh = mock_refresh

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

    def make_result(*, scalar=None, rows=None, scalars_list=None):
        r = MagicMock()
        r.scalar_one_or_none.return_value = scalar
        r.all.return_value = rows or []
        r.scalars.return_value.all.return_value = scalars_list or []
        return r

    mock_db.execute.side_effect = [
        make_result(rows=[(agent, None)]),  # get_agent (auth): list_with_permissions
        make_result(scalars_list=[]),  # get_agent (auth): list_all_subagent_data
        make_result(scalar=agent),  # get_or_404: repository.get
        make_result(rows=[(agent, None)]),  # get_agent (return): list_with_permissions
        make_result(scalars_list=[]),  # get_agent (return): list_all_subagent_data
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

    mock_result = MagicMock()
    mock_result.all.return_value = []
    mock_db.execute.return_value = mock_result

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

    def make_result(*, rows=None, scalars_list=None):
        r = MagicMock()
        r.all.return_value = rows or []
        r.scalars.return_value.all.return_value = scalars_list or []
        return r

    mock_db.execute.side_effect = [
        make_result(rows=[(agent, None, None)]),  # list_with_permissions: no grant
        make_result(scalars_list=[]),  # list_all_subagent_data
    ]

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

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = agent
    mock_db.execute.return_value = mock_result

    response = client.delete(f"/agents/{agent_id}")
    assert response.status_code == 204
    assert agent.is_archived is True


@pytest.mark.usefixtures("current_user")
def test_delete_agent_not_found(client: TestClient, mock_db):
    """Test deleting a non-existent agent returns 404."""
    fake_id = uuid4()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = mock_result

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

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = agent
    mock_db.execute.return_value = mock_result

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

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = agent
    mock_db.execute.return_value = mock_result

    response = client.delete(f"/agents/{agent.id}")
    assert response.status_code == 204
    assert agent.is_archived is True


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
    mock_result = MagicMock()
    mock_result.all.return_value = [(agent, None)]
    mock_result.scalar_one_or_none.return_value = agent
    mock_db.execute.return_value = mock_result

    response = client.post(f"/agents/{agent.id}/restore")
    assert response.status_code == 200
    assert agent.is_archived is False


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
    mock_result = MagicMock()
    mock_result.all.return_value = [(agent, None)]
    mock_db.execute.return_value = mock_result

    response = client.delete(f"/agents/{agent.id}/permanent")
    assert response.status_code == 403


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

    def make_result(*, rows=None, scalars_list=None):
        r = MagicMock()
        r.all.return_value = rows or []
        r.scalars.return_value.all.return_value = scalars_list or []
        return r

    mock_db.execute.side_effect = [
        # get_agent: list_with_permissions returns the agent owned by current_user
        make_result(rows=[(agent, None, None)]),
        # get_agent: list_all_subagent_data
        make_result(scalars_list=[]),
        # ThreadRepository.list_for_agent
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
    assert len(data) == 1
    assert data[0]["user_email"] == "viewer@test.com"
    assert data[0]["source"] == ThreadSource.slack.value


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

    def make_result(*, rows=None, scalars_list=None):
        r = MagicMock()
        r.all.return_value = rows or []
        r.scalars.return_value.all.return_value = scalars_list or []
        return r

    mock_db.execute.side_effect = [
        # list_with_permissions returns the agent but no permission grant
        make_result(rows=[(agent, None, None)]),
        make_result(scalars_list=[]),
    ]

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

    def make_result(*, rows=None, scalars_list=None):
        r = MagicMock()
        r.all.return_value = rows or []
        r.scalars.return_value.all.return_value = scalars_list or []
        return r

    mock_db.execute.side_effect = [
        make_result(rows=[(agent, None, None)]),
        make_result(scalars_list=[]),
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
    assert len(response.json()) == 1


def test_list_agent_threads_requires_auth(client: TestClient):
    response = client.get(f"/agents/{uuid4()}/threads")
    assert response.status_code == 401
