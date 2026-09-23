"""TriggerService.run_now — the owner-credential OAuth gate.

`run_now` gates *before* creating the fire thread so a refused request leaves
no orphan thread behind; it then launches with `preflight_oauth=False` because
the question was just answered.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

import app.triggers.service as triggers_mod
from app.exceptions import DomainValidationError
from app.triggers.service import TriggerService
from app.users.models import WorkspaceRole


def _service():
    trigger = SimpleNamespace(
        id=uuid4(),
        owner_id=uuid4(),
        agent_id=uuid4(),
        instructions="do it",
        name="t",
        model_id="m",
        reasoning_effort=None,
    )
    svc = TriggerService(AsyncMock())
    svc.get_or_404 = AsyncMock(return_value=trigger)
    svc.db.get = AsyncMock(return_value=MagicMock(is_archived=False))  # the agent
    svc.model_service = AsyncMock()  # model availability is not under test here
    svc.thread_service = MagicMock(
        create=AsyncMock(return_value=SimpleNamespace(id="th1"))
    )
    # Caller is an ADMIN, not the owner — the gate must still probe the
    # owner's credentials (the run executes as them).
    user = SimpleNamespace(id=uuid4(), role=WorkspaceRole.admin)
    return svc, trigger, user


def _patch_gate_and_launch(monkeypatch, gate: AsyncMock) -> AsyncMock:
    """`gate` stands in for `preflight.required_oauth_url`; returns the
    `launch` recorder, whose result is run1."""
    monkeypatch.setattr(triggers_mod, "required_oauth_url", gate)
    launched = AsyncMock(return_value=SimpleNamespace(id="run1"))
    monkeypatch.setattr(triggers_mod, "launch", launched)
    return launched


async def test_run_now_rejects_when_owner_mcp_unauthorized(monkeypatch):
    svc, trigger, user = _service()
    gate = AsyncMock(return_value="https://auth.example")
    launched = _patch_gate_and_launch(monkeypatch, gate)

    with pytest.raises(DomainValidationError, match="reconnect"):
        await svc.run_now(trigger.id, user)

    gate.assert_awaited_once_with(svc.db, trigger.agent_id, str(trigger.owner_id))
    # Rejected before any side effect: no fire thread, no run.
    svc.thread_service.create.assert_not_awaited()
    launched.assert_not_awaited()


async def test_run_now_launches_as_the_owner_when_authorized(monkeypatch):
    svc, trigger, user = _service()
    gate = AsyncMock(return_value=None)
    launched = _patch_gate_and_launch(monkeypatch, gate)

    result = await svc.run_now(trigger.id, user)

    gate.assert_awaited_once()
    assert result.thread_id == "th1"
    assert result.run_id == "run1"
    launched.assert_awaited_once()
    request = launched.await_args.args[0]
    assert (request.thread_id, request.user_id) == ("th1", str(trigger.owner_id))
    assert request.input == {"messages": [{"type": "human", "content": "do it"}]}
    # Gated above, before the thread existed — not probed a second time.
    assert launched.await_args.kwargs == {"preflight_oauth": False}
