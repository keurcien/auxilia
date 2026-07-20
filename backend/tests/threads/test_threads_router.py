from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage

from app.agents.structured_output import STRUCTURED_OUTPUT_FLAG
from app.threads.models import ThreadDB, ThreadSource


@pytest.fixture(autouse=True)
def _model_available():
    """These tests cover the thread routes, not model availability — pin the
    server-computed `model_available` flag to True so they don't depend on
    the whitelist or provider env keys."""
    with patch("app.threads.service.ModelService") as model_service_cls:
        model_service_cls.return_value.is_available = AsyncMock(return_value=True)
        yield


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
    # TestClient defaults to no cookies/bearer, but get_current_user is
    # overridden, so detect_auth_method falls through to "bearer" and the
    # server tags the thread as API-created.
    assert data["source"] == ThreadSource.api.value


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

    count_result = MagicMock()
    count_result.scalar_one.return_value = 2
    rows_result = MagicMock()
    rows_result.all.return_value = [
        (thread2, "Test Agent", "🤖", None, False),
        (thread1, "Test Agent", "🤖", None, False),
    ]
    mock_db.execute.side_effect = [count_result, rows_result]

    response = client.get("/threads/")
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 2
    assert data["total"] == 2
    assert data["limit"] == 50
    assert data["offset"] == 0


def test_get_threads_echoes_page_params(client: TestClient, mock_db, current_user):
    """limit/offset are echoed in the envelope; total is the unpaginated count."""
    count_result = MagicMock()
    count_result.scalar_one.return_value = 42
    rows_result = MagicMock()
    rows_result.all.return_value = []
    mock_db.execute.side_effect = [count_result, rows_result]

    response = client.get("/threads/", params={"limit": 10, "offset": 20})
    assert response.status_code == 200
    data = response.json()
    assert data == {"items": [], "total": 42, "limit": 10, "offset": 20}


@pytest.mark.usefixtures("current_user")
def test_get_threads_rejects_invalid_page_params(client: TestClient):
    assert client.get("/threads/", params={"limit": 0}).status_code == 422
    assert client.get("/threads/", params={"limit": 201}).status_code == 422
    assert client.get("/threads/", params={"offset": -1}).status_code == 422


@patch("app.threads.router.get_checkpointer")
def test_get_thread(mock_checkpointer, client: TestClient, mock_db, current_user):
    """Owner can read their own thread."""
    thread_id = str(uuid4())
    agent_id = uuid4()
    thread = ThreadDB(
        id=thread_id,
        user_id=current_user.id,
        agent_id=agent_id,
        first_message_content="Test thread",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = thread
    mock_result.one_or_none.return_value = (thread, "Test Agent", "🤖", None, False)
    mock_db.execute.return_value = mock_result

    mock_saver_instance = AsyncMock()
    mock_saver_instance.aget_tuple = AsyncMock(return_value=None)
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
    assert data["viewer_role"] is None


@patch("app.threads.router.get_checkpointer")
def test_get_thread_hides_structured_output_artifacts(
    mock_checkpointer, client: TestClient, mock_db, current_user
):
    """Formatting-turn messages are filtered out of both message payloads and
    the parsed object is exposed under values.structured_response instead."""
    thread_id = str(uuid4())
    thread = ThreadDB(
        id=thread_id,
        user_id=current_user.id,
        agent_id=uuid4(),
        first_message_content="Test thread",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = thread
    mock_result.one_or_none.return_value = (thread, "Test Agent", "🤖", None, False)
    mock_db.execute.return_value = mock_result

    checkpoint_tuple = MagicMock()
    checkpoint_tuple.checkpoint = {
        "channel_values": {
            "messages": [
                HumanMessage("What is 2 + 2?"),
                AIMessage("2 + 2 = 4"),
                AIMessage(
                    '{"answer": 4}',
                    response_metadata={STRUCTURED_OUTPUT_FLAG: True},
                ),
            ],
            "structured_response": {"answer": 4},
        }
    }
    checkpoint_tuple.pending_writes = []
    mock_saver_instance = AsyncMock()
    mock_saver_instance.aget_tuple = AsyncMock(return_value=checkpoint_tuple)
    mock_checkpointer.return_value.__aenter__ = AsyncMock(
        return_value=mock_saver_instance
    )
    mock_checkpointer.return_value.__aexit__ = AsyncMock(return_value=None)

    response = client.get(f"/threads/{thread_id}")
    assert response.status_code == 200
    data = response.json()

    raw_messages = data["values"]["messages"]
    assert len(raw_messages) == 2
    assert all('{"answer": 4}' not in str(m.get("content")) for m in raw_messages)
    assert data["values"]["structured_response"] == {"answer": 4}


@pytest.mark.usefixtures("current_user")
def test_get_thread_forbidden_for_non_owner(client: TestClient, mock_db):
    """A non-owner without admin access gets a 403."""
    thread_id = str(uuid4())
    agent_id = uuid4()
    other_user_id = uuid4()
    thread = ThreadDB(
        id=thread_id,
        user_id=other_user_id,
        agent_id=agent_id,
        first_message_content="Someone else's thread",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = thread
    # The agent permission lookup returns no rows for a regular member.
    mock_result.all.return_value = []
    mock_db.execute.return_value = mock_result

    response = client.get(f"/threads/{thread_id}")
    assert response.status_code in (403, 404)


@pytest.mark.usefixtures("current_user")
def test_get_thread_not_found(client: TestClient, mock_db):
    """Test getting a non-existent thread returns 404."""
    fake_id = uuid4()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_result.one_or_none.return_value = None
    mock_db.execute.return_value = mock_result

    response = client.get(f"/threads/{fake_id}")
    assert response.status_code == 404
    assert response.json()["detail"] == "Thread not found"


def test_update_thread(client: TestClient, mock_db, current_user):
    """Owner can rename their own thread (updates first_message_content only)."""
    thread_id = str(uuid4())
    agent_id = uuid4()
    thread = ThreadDB(
        id=thread_id,
        user_id=current_user.id,
        agent_id=agent_id,
        first_message_content="Old title",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = thread
    mock_result.one_or_none.return_value = (thread, "Test Agent", "🤖", None, False)
    mock_db.execute.return_value = mock_result

    async def mock_refresh(obj):
        pass

    mock_db.refresh = mock_refresh

    response = client.patch(
        f"/threads/{thread_id}", json={"first_message_content": "New title"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["first_message_content"] == "New title"
    assert thread.first_message_content == "New title"


def test_update_thread_ignores_model_id(client: TestClient, mock_db, current_user):
    """Rename is cosmetic: a `model_id` in the body must not mutate the thread."""
    thread_id = str(uuid4())
    thread = ThreadDB(
        id=thread_id,
        user_id=current_user.id,
        agent_id=uuid4(),
        model_id="claude-opus-4-8",
        first_message_content="Old title",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = thread
    mock_result.one_or_none.return_value = (thread, "Test Agent", "🤖", None, False)
    mock_db.execute.return_value = mock_result

    async def mock_refresh(obj):
        pass

    mock_db.refresh = mock_refresh

    response = client.patch(
        f"/threads/{thread_id}",
        json={"first_message_content": "New title", "model_id": "bogus-model"},
    )
    assert response.status_code == 200
    assert thread.first_message_content == "New title"
    assert thread.model_id == "claude-opus-4-8"


@pytest.mark.usefixtures("current_user")
def test_update_thread_forbidden_for_non_owner(client: TestClient, mock_db):
    """A non-owner cannot rename a thread."""
    thread_id = str(uuid4())
    thread = ThreadDB(
        id=thread_id,
        user_id=uuid4(),
        agent_id=uuid4(),
        first_message_content="Someone else's thread",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = thread
    mock_db.execute.return_value = mock_result

    response = client.patch(
        f"/threads/{thread_id}", json={"first_message_content": "Hijacked"}
    )
    assert response.status_code == 403


@pytest.mark.usefixtures("current_user")
def test_update_thread_not_found(client: TestClient, mock_db):
    """Renaming a non-existent thread returns 404."""
    fake_id = uuid4()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = mock_result

    response = client.patch(
        f"/threads/{fake_id}", json={"first_message_content": "New title"}
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Thread not found"


@patch("app.threads.router.get_checkpointer")
def test_delete_thread(mock_checkpointer, client: TestClient, mock_db, current_user):
    """Test deleting a thread."""
    thread_id = str(uuid4())
    agent_id = uuid4()
    thread = ThreadDB(
        id=thread_id,
        user_id=current_user.id,
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


@pytest.mark.usefixtures("current_user")
@patch("app.threads.router.get_checkpointer")
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
