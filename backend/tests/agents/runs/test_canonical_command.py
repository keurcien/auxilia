"""`RunService.create` canonicalizes an addressed HITL resume (P3-6).

An addressed resume — ``{"resume": {"interrupt_id": ..., "decisions":
[...]}}`` — is validated against the thread's checkpoint and stored in its
canonical, replayable form. Legacy positional resumes and plain inputs never
touch the checkpointer at all.
"""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from langchain_core.messages import AIMessage

import app.agents.runs.service as service_mod
from app.agents.runs.service import RunService
from app.exceptions import StaleApprovalError
from app.threads.models import ThreadDB


INTERRUPT_ID = "ab" * 16


def _paused_checkpoint():
    ai = AIMessage(
        content="",
        tool_calls=[
            {"id": "call_1", "name": "get_weather", "args": {"city": "Paris"}},
            {"id": "call_2", "name": "send_email", "args": {"to": "a@b.c"}},
        ],
    )
    return SimpleNamespace(
        pending_writes=[
            (
                "task-1",
                "__interrupt__",
                [
                    SimpleNamespace(
                        id=INTERRUPT_ID,
                        value={
                            "action_requests": [
                                {"name": "get_weather", "args": {"city": "Paris"}},
                                {"name": "send_email", "args": {"to": "a@b.c"}},
                            ]
                        },
                    )
                ],
            )
        ],
        checkpoint={"channel_values": {"messages": [ai]}},
    )


@pytest.fixture
def service(run_db, monkeypatch):
    """A RunService whose checkpointer serves `_paused_checkpoint` at the root
    (and nothing under any subagent namespace), counting reads."""
    monkeypatch.setattr(
        service_mod.ModelService, "list_whitelisted", AsyncMock(return_value=[])
    )
    reads = {"count": 0}

    @asynccontextmanager
    async def _checkpointer():
        async def _aget_tuple(config):
            reads["count"] += 1
            if config["configurable"].get("checkpoint_ns"):
                return None
            return _paused_checkpoint()

        yield SimpleNamespace(aget_tuple=_aget_tuple)

    monkeypatch.setattr(service_mod, "get_checkpointer", _checkpointer)
    svc = RunService(redis=MagicMock())
    svc._checkpoint_reads = reads  # test-only counter
    return svc


async def _seed_thread(run_db, thread_id="t1"):
    async with run_db() as db:
        db.add(
            ThreadDB(
                id=thread_id,
                agent_id=UUID(int=1),
                user_id=UUID(int=2),
            )
        )
        await db.commit()


async def test_addressed_resume_is_stored_canonical(service, run_db):
    await _seed_thread(run_db)
    run = await service.create(
        thread_id="t1",
        user_id="00000000-0000-0000-0000-000000000002",
        command={
            "resume": {
                "interrupt_id": INTERRUPT_ID,
                "decisions": [
                    {"tool_call_id": "call_2", "type": "reject"},
                    {"tool_call_id": "call_1", "type": "approve"},
                ],
            }
        },
    )
    # Stored id-keyed and re-ordered to the checkpoint's action_requests order.
    assert run.command == {
        "resume": {
            INTERRUPT_ID: {"decisions": [{"type": "approve"}, {"type": "reject"}]}
        }
    }
    # The root checkpoint, plus one probe for a subagent namespace under the
    # interrupting task (`hitl.load_interrupt_scope`) — nothing more.
    assert service._checkpoint_reads["count"] == 2


async def test_stale_addressed_resume_is_rejected_before_a_run_row_exists(
    service, run_db
):
    await _seed_thread(run_db)
    with pytest.raises(StaleApprovalError):
        await service.create(
            thread_id="t1",
            user_id="00000000-0000-0000-0000-000000000002",
            command={"resume": {"interrupt_id": "cd" * 16, "decisions": []}},
        )
    async with run_db() as db:
        from sqlalchemy import select

        from app.agents.runs.models import RunDB

        stmt = select(RunDB)
        assert (await db.execute(stmt)).scalars().all() == []


async def test_legacy_positional_resume_passes_through_without_a_checkpoint_read(
    service, run_db
):
    await _seed_thread(run_db)
    legacy = {"resume": {"decisions": [{"type": "approve"}]}}
    run = await service.create(
        thread_id="t1",
        user_id="00000000-0000-0000-0000-000000000002",
        command=legacy,
    )
    assert run.command == legacy
    assert service._checkpoint_reads["count"] == 0


async def test_replayed_canonical_command_passes_through(service, run_db):
    await _seed_thread(run_db)
    canonical = {"resume": {INTERRUPT_ID: {"decisions": [{"type": "approve"}]}}}
    run = await service.create(
        thread_id="t1",
        user_id="00000000-0000-0000-0000-000000000002",
        command=canonical,
    )
    assert run.command == canonical
    assert service._checkpoint_reads["count"] == 0
