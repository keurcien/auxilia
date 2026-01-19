from datetime import datetime
from unittest.mock import MagicMock
from uuid import uuid4

from fastapi.testclient import TestClient

from app.agents.models import AgentDB


def test_create_agent(client: TestClient, mock_db):
    """Test creating a new agent."""
    owner_id = uuid4()
    agent_data = {
        "name": "Test Agent",
        "instructions": "You are a helpful assistant.",
        "owner_id": str(owner_id),
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
    assert data["owner_id"] == agent_data["owner_id"]
    assert "id" in data
    assert "created_at" in data
    assert "updated_at" in data


def test_get_agents(client: TestClient, mock_db):
    """Test getting all agents."""
    owner_id = uuid4()
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
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [agent1, agent2]
    mock_result.scalars.return_value = mock_scalars
    mock_db.execute.return_value = mock_result

    response = client.get("/agents/")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2


def test_get_agents_filter_by_owner(client: TestClient, mock_db):
    """Test getting agents filtered by owner_id."""
    owner_id = uuid4()
    agent = AgentDB(
        id=uuid4(),
        name="Agent 1",
        instructions="Agent for user 1",
        owner_id=owner_id,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    mock_result = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [agent]
    mock_result.scalars.return_value = mock_scalars
    mock_db.execute.return_value = mock_result

    response = client.get(f"/agents/?owner_id={owner_id}")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["name"] == agent.name


def test_get_agent(client: TestClient, mock_db):
    """Test getting a single agent by ID."""
    agent_id = uuid4()
    owner_id = uuid4()
    agent = AgentDB(
        id=agent_id,
        name="Test Agent",
        instructions="Test instructions",
        owner_id=owner_id,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    # Mock the read_agent utility function
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = agent
    mock_db.execute.return_value = mock_result

    response = client.get(f"/agents/{agent_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(agent_id)
    assert data["name"] == agent.name


def test_get_agent_not_found(client: TestClient, mock_db):
    """Test getting a non-existent agent returns 404."""
    fake_id = uuid4()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = mock_result

    response = client.get(f"/agents/{fake_id}")
    assert response.status_code == 404
    assert response.json()["detail"] == "Agent not found"


def test_update_agent(client: TestClient, mock_db):
    """Test updating an agent."""
    agent_id = uuid4()
    owner_id = uuid4()
    agent = AgentDB(
        id=agent_id,
        name="Original Agent",
        instructions="Original instructions",
        owner_id=owner_id,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = agent
    mock_db.execute.return_value = mock_result

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


def test_update_agent_not_found(client: TestClient, mock_db):
    """Test updating a non-existent agent returns 404."""
    fake_id = uuid4()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = mock_result

    update_data = {"name": "Updated Name"}
    response = client.patch(f"/agents/{fake_id}", json=update_data)
    assert response.status_code == 404
    assert response.json()["detail"] == "Agent not found"


def test_delete_agent(client: TestClient, mock_db):
    """Test deleting an agent."""
    agent_id = uuid4()
    owner_id = uuid4()
    agent = AgentDB(
        id=agent_id,
        name="Agent to Delete",
        instructions="This agent will be deleted",
        owner_id=owner_id,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = agent
    mock_db.execute.return_value = mock_result

    response = client.delete(f"/agents/{agent_id}")
    assert response.status_code == 204
    mock_db.delete.assert_called_once()


def test_delete_agent_not_found(client: TestClient, mock_db):
    """Test deleting a non-existent agent returns 404."""
    fake_id = uuid4()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = mock_result

    response = client.delete(f"/agents/{fake_id}")
    assert response.status_code == 404
    assert response.json()["detail"] == "Agent not found"
