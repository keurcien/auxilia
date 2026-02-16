from uuid import uuid4
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
from app.threads.models import ThreadDB


def test_create_thread(client: TestClient, mock_db, current_user):
    """Test creating a new thread."""
    user_id = current_user.id
    agent_id = uuid4()

    thread_data = {
        "user_id": str(user_id),
        "agent_id": str(agent_id),
        "first_message_content": "Hello, this is the first message",
    }

    # Mock refresh to populate the created thread with generated fields
    async def mock_refresh(obj):
        obj.id = str(uuid4())
        obj.created_at = datetime.now()
        obj.updated_at = datetime.now()

    mock_db.refresh = mock_refresh

    response = client.post("/threads/", json=thread_data)

    assert response.status_code == 200
    data = response.json()
    assert data["user_id"] == thread_data["user_id"]
    assert data["agent_id"] == thread_data["agent_id"]
    assert data["first_message_content"] == thread_data["first_message_content"]
    assert "id" in data
    assert "created_at" in data
    assert "updated_at" in data


def test_create_thread_without_first_message(client: TestClient, mock_db, current_user):
    """Test creating a thread without first_message_content."""
    user_id = current_user.id
    agent_id = uuid4()
    thread_data = {
        "user_id": str(user_id),
        "agent_id": str(agent_id),
    }

    # Mock refresh to populate the created thread with generated fields
    async def mock_refresh(obj):
        obj.id = str(uuid4())
        obj.created_at = datetime.now()
        obj.updated_at = datetime.now()

    mock_db.refresh = mock_refresh

    response = client.post("/threads/", json=thread_data)

    assert response.status_code == 200
    data = response.json()
    assert data["user_id"] == thread_data["user_id"]
    assert data["agent_id"] == thread_data["agent_id"]
    assert data["first_message_content"] is None


def test_get_threads(client: TestClient, mock_db, current_user):
    """Test getting all threads."""
    user_id = current_user.id
    agent_id = uuid4()
    thread1 = ThreadDB(
        id=str(uuid4()),
        user_id=user_id,
        agent_id=agent_id,
        first_message_content="First thread",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    thread2 = ThreadDB(
        id=str(uuid4()),
        user_id=user_id,
        agent_id=agent_id,
        first_message_content="Second thread",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    mock_result = MagicMock()
    mock_result.all.return_value = [
        (thread2, "Test Agent", "🤖"),
        (thread1, "Test Agent", "🤖"),
    ]
    mock_db.execute.return_value = mock_result

    response = client.get("/threads/")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2


@patch("app.threads.router.AsyncPostgresSaver.from_conn_string")
def test_get_thread(mock_checkpointer, client: TestClient, mock_db):
    """Test getting a single thread by ID."""
    thread_id = str(uuid4())
    user_id = uuid4()
    agent_id = uuid4()
    thread = ThreadDB(
        id=thread_id,
        user_id=user_id,
        agent_id=agent_id,
        first_message_content="Test thread",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = thread
    mock_db.execute.return_value = mock_result

    # Mock the checkpointer context manager
    mock_saver_instance = AsyncMock()
    mock_saver_instance.aget = AsyncMock(return_value=None)
    mock_checkpointer.return_value.__aenter__ = AsyncMock(
        return_value=mock_saver_instance
    )
    mock_checkpointer.return_value.__aexit__ = AsyncMock(return_value=None)

    response = client.get(f"/threads/{thread_id}")
    assert response.status_code == 200
    data = response.json()
    assert "thread" in data
    assert "messages" in data
    assert data["thread"]["id"] == thread_id
    assert data["messages"] == []


def test_get_thread_not_found(client: TestClient, mock_db):
    """Test getting a non-existent thread returns 404."""
    fake_id = uuid4()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = mock_result

    response = client.get(f"/threads/{fake_id}")
    assert response.status_code == 404
    assert response.json()["detail"] == "Thread not found"


@patch("app.threads.router.AsyncPostgresSaver.from_conn_string")
def test_delete_thread(mock_checkpointer, client: TestClient, mock_db):
    """Test deleting a thread."""
    thread_id = str(uuid4())
    user_id = uuid4()
    agent_id = uuid4()
    thread = ThreadDB(
        id=thread_id,
        user_id=user_id,
        agent_id=agent_id,
        first_message_content="Thread to delete",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = thread
    mock_db.execute.return_value = mock_result

    # Mock the checkpointer context manager
    mock_saver_instance = AsyncMock()
    mock_saver_instance.adelete_thread = AsyncMock()
    mock_checkpointer.return_value.__aenter__ = AsyncMock(
        return_value=mock_saver_instance
    )
    mock_checkpointer.return_value.__aexit__ = AsyncMock(return_value=None)

    response = client.delete(f"/threads/{thread_id}")
    assert response.status_code == 204
    mock_db.delete.assert_called_once()


@patch("app.threads.router.AsyncPostgresSaver.from_conn_string")
def test_delete_thread_not_found(mock_checkpointer, client: TestClient, mock_db):
    """Test deleting a non-existent thread returns 404."""
    fake_id = uuid4()

    # Mock the checkpointer context manager
    mock_saver_instance = AsyncMock()
    mock_saver_instance.adelete_thread = AsyncMock()
    mock_checkpointer.return_value.__aenter__ = AsyncMock(
        return_value=mock_saver_instance
    )
    mock_checkpointer.return_value.__aexit__ = AsyncMock(return_value=None)

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = mock_result

    response = client.delete(f"/threads/{fake_id}")
    assert response.status_code == 404
    assert response.json()["detail"] == "Thread not found"
