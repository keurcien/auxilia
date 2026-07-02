from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi.testclient import TestClient

from app.agents.runs.router import get_run_service
from app.agents.runs.state import RunRecord, RunStatus
from app.main import app
from app.threads.models import ThreadDB


def _owned_thread(current_user) -> ThreadDB:
    return ThreadDB(
        id=str(uuid4()),
        user_id=current_user.id,
        agent_id=uuid4(),
        first_message_content="run",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )


class _FakeRunService:
    """Stands in for RunService: records create() and returns canned records."""

    def __init__(
        self, terminal: RunStatus = RunStatus.success, error: str | None = None
    ):
        self.create_kwargs: dict | None = None
        self._terminal = terminal
        self._error = error

    async def create(self, **kwargs) -> RunRecord:
        self.create_kwargs = kwargs
        return RunRecord(
            id="run1", thread_id=kwargs["thread_id"], user_id=kwargs["user_id"]
        )

    async def wait_for_terminal(self, run_id: str) -> RunRecord:
        return RunRecord(
            id=run_id,
            thread_id="t1",
            user_id="u1",
            status=self._terminal,
            error=self._error,
        )


def _mock_thread_lookup(mock_db, thread: ThreadDB) -> None:
    result = MagicMock()
    result.scalar_one_or_none.return_value = thread
    mock_db.execute.return_value = result


@patch("app.agents.runs.router.read_run_result", new_callable=AsyncMock)
def test_invoke_creates_run_and_returns_result(
    mock_read, client: TestClient, mock_db, current_user
):
    """invoke forwards output_schema into the run and returns the awaited result."""
    thread = _owned_thread(current_user)
    _mock_thread_lookup(mock_db, thread)
    mock_read.return_value = {
        "content": '{"answer": 42}',
        "structured_response": {"answer": 42},
    }
    fake = _FakeRunService()
    app.dependency_overrides[get_run_service] = lambda: fake

    schema = {"type": "object", "properties": {"answer": {"type": "integer"}}}
    try:
        response = client.post(
            f"/threads/{thread.id}/runs/invoke",
            json={
                "input": {"messages": [{"type": "human", "content": "hi"}]},
                "output_schema": schema,
            },
        )
    finally:
        app.dependency_overrides.pop(get_run_service, None)

    assert response.status_code == 200
    assert response.json()["structured_response"] == {"answer": 42}
    assert fake.create_kwargs["output_schema"] == schema


@patch("app.agents.runs.router.read_run_result", new_callable=AsyncMock)
def test_invoke_without_output_schema(
    mock_read, client: TestClient, mock_db, current_user
):
    thread = _owned_thread(current_user)
    _mock_thread_lookup(mock_db, thread)
    mock_read.return_value = {"content": "hello", "structured_response": None}
    fake = _FakeRunService()
    app.dependency_overrides[get_run_service] = lambda: fake

    try:
        response = client.post(
            f"/threads/{thread.id}/runs/invoke",
            json={"input": {"messages": [{"type": "human", "content": "hi"}]}},
        )
    finally:
        app.dependency_overrides.pop(get_run_service, None)

    assert response.status_code == 200
    assert response.json()["content"] == "hello"
    assert fake.create_kwargs["output_schema"] is None


@patch("app.agents.runs.router.read_run_result", new_callable=AsyncMock)
def test_invoke_schema_violating_result_is_500(
    mock_read, client: TestClient, mock_db, current_user
):
    """A run that ends success without a schema-valid structured response must
    error out, not hand the caller an empty/stale object."""
    thread = _owned_thread(current_user)
    _mock_thread_lookup(mock_db, thread)
    mock_read.return_value = {"content": "prose", "structured_response": {}}
    fake = _FakeRunService()
    app.dependency_overrides[get_run_service] = lambda: fake

    schema = {
        "type": "object",
        "properties": {"answer": {"type": "integer"}},
        "required": ["answer"],
    }
    try:
        response = client.post(
            f"/threads/{thread.id}/runs/invoke",
            json={
                "input": {"messages": [{"type": "human", "content": "hi"}]},
                "output_schema": schema,
            },
        )
    finally:
        app.dependency_overrides.pop(get_run_service, None)

    assert response.status_code == 500
    assert "valid structured response" in response.json()["detail"]


def test_invoke_failed_run_is_500(client: TestClient, mock_db, current_user):
    thread = _owned_thread(current_user)
    _mock_thread_lookup(mock_db, thread)
    fake = _FakeRunService(terminal=RunStatus.error, error="boom")
    app.dependency_overrides[get_run_service] = lambda: fake

    try:
        response = client.post(
            f"/threads/{thread.id}/runs/invoke",
            json={"input": {"messages": [{"type": "human", "content": "hi"}]}},
        )
    finally:
        app.dependency_overrides.pop(get_run_service, None)

    assert response.status_code == 500
    assert response.json()["detail"] == "boom"


def test_invoke_non_success_terminal_is_500(client: TestClient, mock_db, current_user):
    """A cancelled/interrupted run must not return partial checkpoint data as success."""
    thread = _owned_thread(current_user)
    _mock_thread_lookup(mock_db, thread)
    fake = _FakeRunService(terminal=RunStatus.cancelled)
    app.dependency_overrides[get_run_service] = lambda: fake

    try:
        response = client.post(
            f"/threads/{thread.id}/runs/invoke",
            json={"input": {"messages": [{"type": "human", "content": "hi"}]}},
        )
    finally:
        app.dependency_overrides.pop(get_run_service, None)

    assert response.status_code == 500
