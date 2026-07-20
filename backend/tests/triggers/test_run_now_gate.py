"""TriggerService.run_now — the owner-credential OAuth gate."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

import app.triggers.service as triggers_mod
from app.exceptions import DomainValidationError
from app.mcp.client.exceptions import OAuthAuthorizationRequired
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


def _fake_run_service_cls(gate: AsyncMock) -> MagicMock:
    """A stand-in for the RunService class: `ensure_mcp_authorized` is the
    gate, instantiating it yields a service whose create() returns run1."""
    return MagicMock(
        ensure_mcp_authorized=gate,
        return_value=MagicMock(
            create=AsyncMock(return_value=SimpleNamespace(id="run1"))
        ),
    )


async def test_run_now_rejects_when_owner_mcp_unauthorized(monkeypatch):
    svc, trigger, user = _service()
    gate = AsyncMock(side_effect=OAuthAuthorizationRequired("https://auth.example"))
    monkeypatch.setattr(triggers_mod, "RunService", _fake_run_service_cls(gate))

    with pytest.raises(DomainValidationError, match="reconnect"):
        await svc.run_now(trigger.id, user)

    gate.assert_awaited_once_with(svc.db, trigger.agent_id, str(trigger.owner_id))
    # Rejected before any side effect: no fire thread, no run.
    svc.thread_service.create.assert_not_awaited()


async def test_run_now_launches_when_owner_authorized(monkeypatch):
    svc, trigger, user = _service()
    gate = AsyncMock(return_value=None)
    monkeypatch.setattr(triggers_mod, "RunService", _fake_run_service_cls(gate))

    result = await svc.run_now(trigger.id, user)

    gate.assert_awaited_once()
    assert result.thread_id == "th1"
    assert result.run_id == "run1"
