from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.threads.models import ThreadDB
from app.threads.service import ThreadService


def _make_service():
    db = AsyncMock()
    db.add = MagicMock()
    db.delete = AsyncMock()
    db.flush = AsyncMock()
    svc = ThreadService(db)
    svc.repository = MagicMock()
    return svc, db


async def test_delete_all_for_agent_deletes_threads_and_checkpoints():
    svc, db = _make_service()
    agent_id = uuid4()
    thread_ids = ["t1", "t2"]
    svc.repository.list_ids_for_agent = AsyncMock(return_value=thread_ids)
    svc.repository.get = AsyncMock(
        side_effect=lambda tid: ThreadDB(id=tid, user_id=uuid4(), agent_id=agent_id)
    )

    checkpointer = AsyncMock()
    with patch("app.threads.service.get_checkpointer") as mock_cp:
        mock_cp.return_value.__aenter__ = AsyncMock(return_value=checkpointer)
        mock_cp.return_value.__aexit__ = AsyncMock(return_value=None)
        await svc.delete_all_for_agent(agent_id)

    assert checkpointer.adelete_thread.await_count == 2
    checkpointer.adelete_thread.assert_any_await(thread_id="t1")
    checkpointer.adelete_thread.assert_any_await(thread_id="t2")
    assert db.delete.await_count == 2
    db.flush.assert_awaited_once()


async def test_delete_all_for_agent_noop_when_no_threads():
    svc, db = _make_service()
    svc.repository.list_ids_for_agent = AsyncMock(return_value=[])

    with patch("app.threads.service.get_checkpointer") as mock_cp:
        await svc.delete_all_for_agent(uuid4())

    mock_cp.assert_not_called()
    db.delete.assert_not_called()
    db.flush.assert_not_called()
