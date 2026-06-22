from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.threads.service import ThreadService


def _make_service():
    db = AsyncMock()
    db.add = MagicMock()
    db.delete = AsyncMock()
    db.flush = AsyncMock()
    svc = ThreadService(db)
    svc.repository = MagicMock()
    return svc, db


# ---------------------------------------------------------------------------
# delete_rows_for_agent
# ---------------------------------------------------------------------------


async def test_delete_rows_for_agent_bulk_deletes_and_returns_ids():
    svc, db = _make_service()
    agent_id = uuid4()
    thread_ids = ["t1", "t2"]
    svc.repository.list_ids_for_agent = AsyncMock(return_value=thread_ids)
    svc.repository.delete_for_agent = AsyncMock()

    result = await svc.delete_rows_for_agent(agent_id)

    assert result == thread_ids
    # One bulk delete, not a per-thread loop (no N+1).
    svc.repository.delete_for_agent.assert_awaited_once_with(agent_id)
    db.flush.assert_awaited_once()


async def test_delete_rows_for_agent_noop_when_no_threads():
    svc, db = _make_service()
    svc.repository.list_ids_for_agent = AsyncMock(return_value=[])
    svc.repository.delete_for_agent = AsyncMock()

    result = await svc.delete_rows_for_agent(uuid4())

    assert result == []
    svc.repository.delete_for_agent.assert_not_called()
    db.flush.assert_not_called()


# ---------------------------------------------------------------------------
# purge_checkpoints
# ---------------------------------------------------------------------------


async def test_purge_checkpoints_deletes_each_thread():
    svc, _ = _make_service()
    checkpointer = AsyncMock()
    with patch("app.threads.service.get_checkpointer") as mock_cp:
        mock_cp.return_value.__aenter__ = AsyncMock(return_value=checkpointer)
        mock_cp.return_value.__aexit__ = AsyncMock(return_value=None)
        await svc.purge_checkpoints(["t1", "t2"])

    assert checkpointer.adelete_thread.await_count == 2
    checkpointer.adelete_thread.assert_any_await(thread_id="t1")
    checkpointer.adelete_thread.assert_any_await(thread_id="t2")


async def test_purge_checkpoints_noop_when_empty():
    svc, _ = _make_service()
    with patch("app.threads.service.get_checkpointer") as mock_cp:
        await svc.purge_checkpoints([])

    mock_cp.assert_not_called()
