"""Protocol endpoint authorization: reads serve the owner and an admin of the
agent (the audience `GET /threads/{id}` serves, so an admin's read-only view
hydrates); commands stay owner-only."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.exceptions import PermissionDeniedError
from app.main import app
from app.runtime.api.router import get_protocol_service
from app.threads.models import ThreadDB


_SNAPSHOT = {"values": {"messages": []}, "next": [], "tasks": []}


class _Protocol:
    async def thread_state(self, thread_id):
        return _SNAPSHOT

    async def message(self, thread_id, message_id):
        return {"id": message_id, "type": "tool", "content": "whole"}


@pytest.fixture
def protocol_stub():
    app.dependency_overrides[get_protocol_service] = lambda: _Protocol()
    yield
    app.dependency_overrides.pop(get_protocol_service, None)


def _someone_elses_thread(mock_db) -> str:
    thread_id = str(uuid4())
    thread = ThreadDB(
        id=thread_id,
        user_id=uuid4(),
        agent_id=uuid4(),
        first_message_content="Someone else's thread",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    result = MagicMock()
    result.scalar_one_or_none.return_value = thread
    mock_db.execute.return_value = result
    return thread_id


_GATE = "app.threads.dependencies.AgentService.require_permission"


@pytest.mark.usefixtures("current_user", "protocol_stub")
def test_an_agent_admin_can_read_another_users_state(client: TestClient, mock_db):
    thread_id = _someone_elses_thread(mock_db)
    with patch(_GATE, new_callable=AsyncMock) as gate:
        response = client.get(f"/threads/{thread_id}/state")
    assert response.status_code == 200
    assert response.json() == _SNAPSHOT
    gate.assert_awaited_once()


@pytest.mark.usefixtures("current_user", "protocol_stub")
def test_an_agent_admin_can_read_a_message(client: TestClient, mock_db):
    thread_id = _someone_elses_thread(mock_db)
    with patch(_GATE, new_callable=AsyncMock):
        response = client.get(f"/threads/{thread_id}/messages/m1")
    assert response.status_code == 200
    assert response.json()["content"] == "whole"


@pytest.mark.usefixtures("current_user", "protocol_stub")
def test_a_stranger_cannot_read_state(client: TestClient, mock_db):
    thread_id = _someone_elses_thread(mock_db)
    with patch(_GATE, new_callable=AsyncMock, side_effect=PermissionDeniedError("no")):
        response = client.get(f"/threads/{thread_id}/state")
    assert response.status_code == 403


@pytest.mark.usefixtures("current_user", "protocol_stub")
def test_commands_stay_owner_only_even_for_an_admin(client: TestClient, mock_db):
    thread_id = _someone_elses_thread(mock_db)
    with patch(_GATE, new_callable=AsyncMock) as gate:
        response = client.post(
            f"/threads/{thread_id}/commands",
            json={"id": 1, "method": "run.start", "params": {}},
        )
    assert response.status_code == 403
    gate.assert_not_awaited()


def test_a_launch_refused_for_oauth_is_the_401_body_and_creates_nothing(
    client: TestClient, mock_db, current_user
):
    """The gate runs inside `launch`, behind `dispatch`; the router renders its
    refusal as the same `{oauth_required, auth_url}` body the run endpoints
    answer — there is no app-global handler for it (design review §2.4)."""
    from app.mcp.client.exceptions import OAuthAuthorizationRequired

    class _Refusing(_Protocol):
        async def dispatch(self, thread_id, user_id, command):
            raise OAuthAuthorizationRequired("https://auth.example/authorize")

    thread = ThreadDB(
        id=str(uuid4()),
        user_id=current_user.id,
        agent_id=uuid4(),
        first_message_content="mine",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    result = MagicMock()
    result.scalar_one_or_none.return_value = thread
    mock_db.execute.return_value = result
    app.dependency_overrides[get_protocol_service] = lambda: _Refusing()
    try:
        response = client.post(
            f"/threads/{thread.id}/commands",
            json={"id": 1, "method": "run.start", "params": {"input": {}}},
        )
    finally:
        app.dependency_overrides.pop(get_protocol_service, None)

    assert response.status_code == 401
    assert response.json() == {
        "error": "oauth_required",
        "auth_url": "https://auth.example/authorize",
    }
