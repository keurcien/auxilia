from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi.testclient import TestClient

from app.agents.runs.models import RunDB
from app.agents.runs.router import get_run_service
from app.agents.runs.state import RunStatus
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
        self.calls: list[str] = []
        self.gate_args: tuple | None = None
        self._terminal = terminal
        self._error = error

    async def ensure_mcp_authorized(self, db, agent_id, user_id) -> None:
        """Records the call: the gate itself is unit-tested in test_gate.py,
        but the router must invoke it (with the thread's identity) BEFORE
        creating the run — that wiring is the point of the gate."""
        self.calls.append("gate")
        self.gate_args = (agent_id, user_id)

    async def create(self, **kwargs) -> RunDB:
        self.calls.append("create")
        self.create_kwargs = kwargs
        return RunDB(
            id="run1",
            thread_id=kwargs["thread_id"],
            user_id=uuid4(),
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

    async def stream(self, run_id: str):
        yield "data: [DONE]\n\n"

    async def wait_for_terminal(self, run_id: str) -> RunDB:
        return RunDB(
            id=run_id,
            thread_id="t1",
            user_id=uuid4(),
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
    assert fake.calls == ["gate", "create"]
    assert fake.gate_args == (thread.agent_id, str(thread.user_id))


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


def test_create_run_gates_before_creating(client: TestClient, mock_db, current_user):
    thread = _owned_thread(current_user)
    _mock_thread_lookup(mock_db, thread)
    fake = _FakeRunService()
    app.dependency_overrides[get_run_service] = lambda: fake

    try:
        response = client.post(
            f"/threads/{thread.id}/runs",
            json={"input": {"messages": [{"type": "human", "content": "hi"}]}},
        )
    finally:
        app.dependency_overrides.pop(get_run_service, None)

    assert response.status_code == 201
    assert fake.calls == ["gate", "create"]
    assert fake.gate_args == (thread.agent_id, str(thread.user_id))


def test_stream_gates_before_creating(client: TestClient, mock_db, current_user):
    thread = _owned_thread(current_user)
    _mock_thread_lookup(mock_db, thread)
    fake = _FakeRunService()
    app.dependency_overrides[get_run_service] = lambda: fake

    try:
        response = client.post(
            f"/threads/{thread.id}/runs/stream",
            json={"input": {"messages": [{"type": "human", "content": "hi"}]}},
        )
    finally:
        app.dependency_overrides.pop(get_run_service, None)

    assert response.status_code == 200
    assert response.headers["x-run-id"] == "run1"
    assert fake.calls == ["gate", "create"]
    assert fake.gate_args == (thread.agent_id, str(thread.user_id))


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
