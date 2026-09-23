"""`launch` — the one seam every ingress crosses.

It canonicalizes an addressed HITL resume against the thread's checkpoint
(P3-6), runs the gates *before* a run row exists, and only then inserts the
record. The gates themselves are unit-tested in `test_preflight.py`; here they
are stubs, so what is under test is the sequence and what each refusal leaves
behind (nothing).
"""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import select

import app.runtime.hitl as hitl_mod
import app.runtime.launch as launch_mod
from app.exceptions import DomainValidationError, NotFoundError, StaleApprovalError
from app.mcp.client.exceptions import OAuthAuthorizationRequired
from app.runtime.checkpoints import EMPTY_STATE
from app.runtime.launch import LaunchRequest, launch
from app.runtime.runs.models import RunDB
from app.runtime.runs.service import RunService
from app.threads.models import ThreadDB
from tests.runtime.fake_checkpoints import checkpoint_state


INTERRUPT_ID = "ab" * 16
USER_ID = "00000000-0000-0000-0000-000000000002"


def _paused_checkpoint():
    ai = AIMessage(
        content="",
        tool_calls=[
            {"id": "call_1", "name": "get_weather", "args": {"city": "Paris"}},
            {"id": "call_2", "name": "send_email", "args": {"to": "a@b.c"}},
        ],
    )
    value = {
        "action_requests": [
            {"name": "get_weather", "args": {"city": "Paris"}},
            {"name": "send_email", "args": {"to": "a@b.c"}},
        ]
    }
    return checkpoint_state([ai], interrupts=[("task-1", value, INTERRUPT_ID)])


@pytest.fixture
def launcher(run_db, monkeypatch):
    """`launch` with stubbed gates and a checkpoint reader that serves
    `_paused_checkpoint` at the root (nothing under any subagent namespace),
    counting reads."""
    monkeypatch.setattr(
        launch_mod.ModelService, "list_whitelisted", AsyncMock(return_value=[])
    )
    ensure_launchable = AsyncMock(return_value=None)
    required_oauth_url = AsyncMock(return_value=None)
    monkeypatch.setattr(launch_mod, "ensure_launchable", ensure_launchable)
    monkeypatch.setattr(launch_mod, "required_oauth_url", required_oauth_url)
    reads = {"count": 0}

    @asynccontextmanager
    async def _checkpointer():
        yield SimpleNamespace()

    async def _get_state(checkpointer, thread_id, checkpoint_ns=""):
        reads["count"] += 1
        return EMPTY_STATE if checkpoint_ns else _paused_checkpoint()

    monkeypatch.setattr(launch_mod, "get_checkpointer", _checkpointer)
    monkeypatch.setattr(hitl_mod, "get_checkpoint_state", _get_state)
    runs = RunService(redis=MagicMock())

    async def _launch(**fields):
        options = {}
        if "preflight_oauth" in fields:
            options["preflight_oauth"] = fields.pop("preflight_oauth")
        return await launch(LaunchRequest(**fields), runs=runs, **options)

    return SimpleNamespace(
        launch=_launch,
        reads=reads,
        ensure_launchable=ensure_launchable,
        required_oauth_url=required_oauth_url,
    )


async def _seed_thread(run_db, thread_id="t1"):
    async with run_db() as db:
        db.add(ThreadDB(id=thread_id, agent_id=UUID(int=1), user_id=UUID(int=2)))
        await db.commit()


async def _run_rows(run_db) -> list[RunDB]:
    async with run_db() as db:
        stmt = select(RunDB)
        return list((await db.execute(stmt)).scalars().all())


# --- HITL resume canonicalization ---------------------------------------------


async def test_addressed_resume_is_stored_canonical(launcher, run_db):
    await _seed_thread(run_db)
    run = await launcher.launch(
        thread_id="t1",
        user_id=USER_ID,
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
    assert launcher.reads["count"] == 2


async def test_stale_addressed_resume_is_rejected_before_a_run_row_exists(
    launcher, run_db
):
    await _seed_thread(run_db)
    with pytest.raises(StaleApprovalError):
        await launcher.launch(
            thread_id="t1",
            user_id=USER_ID,
            command={"resume": {"interrupt_id": "cd" * 16, "decisions": []}},
        )
    assert await _run_rows(run_db) == []
    # Refused before the gates ran, let alone a session opened.
    launcher.ensure_launchable.assert_not_awaited()


async def test_legacy_positional_resume_passes_through_without_a_checkpoint_read(
    launcher, run_db
):
    await _seed_thread(run_db)
    legacy = {"resume": {"decisions": [{"type": "approve"}]}}
    run = await launcher.launch(thread_id="t1", user_id=USER_ID, command=legacy)
    assert run.command == legacy
    assert launcher.reads["count"] == 0


async def test_replayed_canonical_command_passes_through(launcher, run_db):
    await _seed_thread(run_db)
    canonical = {"resume": {INTERRUPT_ID: {"decisions": [{"type": "approve"}]}}}
    run = await launcher.launch(thread_id="t1", user_id=USER_ID, command=canonical)
    assert run.command == canonical
    assert launcher.reads["count"] == 0


# --- gates -----------------------------------------------------------------------


async def test_input_and_command_are_exclusive(launcher, run_db):
    await _seed_thread(run_db)
    with pytest.raises(DomainValidationError, match="either input or command"):
        await launcher.launch(
            thread_id="t1",
            user_id=USER_ID,
            input={"messages": []},
            command={"resume": {}},
        )
    assert await _run_rows(run_db) == []


async def test_unknown_thread_is_not_found(launcher, run_db):
    with pytest.raises(NotFoundError):
        await launcher.launch(thread_id="ghost", user_id=USER_ID, input={})
    assert await _run_rows(run_db) == []


async def test_gates_run_before_the_run_row_exists(launcher, run_db):
    """A gate refusal (model disabled, sandbox down) is the ingress's 409 —
    it must never become a failed run the user has to discover."""
    await _seed_thread(run_db)
    launcher.ensure_launchable.side_effect = DomainValidationError("model off")
    with pytest.raises(DomainValidationError, match="model off"):
        await launcher.launch(thread_id="t1", user_id=USER_ID, input={})
    assert await _run_rows(run_db) == []
    launcher.required_oauth_url.assert_not_awaited()


async def test_oauth_refusal_carries_the_url_and_creates_nothing(launcher, run_db):
    """`required_oauth_url` returns the URL; `launch` turns it into the one
    exception every ingress renders its own way (401 body, Slack prompt,
    rejected trigger)."""
    await _seed_thread(run_db)
    launcher.required_oauth_url.return_value = "https://auth.example/authorize"
    with pytest.raises(OAuthAuthorizationRequired) as excinfo:
        await launcher.launch(thread_id="t1", user_id=USER_ID, input={})
    assert excinfo.value.url == "https://auth.example/authorize"
    assert await _run_rows(run_db) == []


async def test_oauth_gate_probes_the_actor_with_the_spec_already_read(launcher, run_db):
    """One graph read per launch: the spec `ensure_launchable` returns is
    handed to the OAuth gate. The actor is the request's user — the trigger
    owner for a firing, not whoever pressed the button."""
    await _seed_thread(run_db)
    spec = SimpleNamespace(all_mcp_bindings=[])
    launcher.ensure_launchable.return_value = spec
    await launcher.launch(thread_id="t1", user_id=USER_ID, input={})
    launcher.required_oauth_url.assert_awaited_once()
    args, kwargs = launcher.required_oauth_url.await_args
    assert args[1:] == (UUID(int=1), USER_ID)
    assert kwargs == {"spec": spec}


async def test_preflight_oauth_false_skips_only_the_oauth_gate(launcher, run_db):
    """An ingress that already answered the OAuth question (Slack, Run now) or
    has nobody to answer to (the scanner) still gets the other gates."""
    await _seed_thread(run_db)
    run = await launcher.launch(
        thread_id="t1", user_id=USER_ID, input={}, preflight_oauth=False
    )
    assert run.status.value == "pending"
    launcher.ensure_launchable.assert_awaited_once()
    launcher.required_oauth_url.assert_not_awaited()
