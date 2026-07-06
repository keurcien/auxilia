from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

from fastapi.testclient import TestClient

from app.threads.models import ThreadDB, ThreadSource
from app.triggers.models import TriggerDB


def _trigger(owner_id) -> TriggerDB:
    return TriggerDB(
        id=uuid4(),
        name="Daily digest",
        instructions="Summarize yesterday's activity",
        agent_id=uuid4(),
        model_id="claude-sonnet-5",
        cron_expression="0 9 * * *",
        timezone="UTC",
        is_active=True,
        owner_id=owner_id,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _fire_thread(trigger: TriggerDB) -> ThreadDB:
    return ThreadDB(
        id=str(uuid4()),
        user_id=trigger.owner_id,
        agent_id=trigger.agent_id,
        first_message_content=trigger.name,
        source=ThreadSource.trigger,
        trigger_id=trigger.id,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _mock_execute_results(mock_db, trigger: TriggerDB | None, threads: list[ThreadDB]):
    """First execute: trigger lookup; second: the trigger's thread list."""
    trigger_result = MagicMock()
    trigger_result.scalar_one_or_none.return_value = trigger
    threads_result = MagicMock()
    threads_result.scalars.return_value.all.return_value = threads
    mock_db.execute.side_effect = [trigger_result, threads_result]


def test_list_trigger_threads_as_owner(client: TestClient, mock_db, current_user):
    trigger = _trigger(owner_id=current_user.id)
    thread = _fire_thread(trigger)
    _mock_execute_results(mock_db, trigger, [thread])

    response = client.get(f"/triggers/{trigger.id}/threads")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == thread.id
    assert data[0]["agent_id"] == str(trigger.agent_id)
    assert data[0]["first_message_content"] == trigger.name


def test_list_trigger_threads_forbidden_for_non_owner(
    client: TestClient, mock_db, current_user
):
    trigger = _trigger(owner_id=uuid4())
    _mock_execute_results(mock_db, trigger, [])

    response = client.get(f"/triggers/{trigger.id}/threads")

    assert response.status_code == 403


def test_list_trigger_threads_as_admin(client: TestClient, mock_db, admin_user):
    trigger = _trigger(owner_id=uuid4())
    thread = _fire_thread(trigger)
    _mock_execute_results(mock_db, trigger, [thread])

    response = client.get(f"/triggers/{trigger.id}/threads")

    assert response.status_code == 200
    assert [t["id"] for t in response.json()] == [thread.id]


def test_list_trigger_threads_not_found(client: TestClient, mock_db, current_user):
    _mock_execute_results(mock_db, None, [])

    response = client.get(f"/triggers/{uuid4()}/threads")

    assert response.status_code == 404
