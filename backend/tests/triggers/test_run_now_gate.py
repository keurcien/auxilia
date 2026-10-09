"""TriggerService.run_now — immediate run creation."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import app.triggers.service as triggers_mod
from app.triggers.service import TriggerService
from app.users.models import WorkspaceRole
from tests.conftest import TEST_WORKSPACE_ID


def _service():
    trigger = SimpleNamespace(
        id=uuid4(),
        workspace_id=TEST_WORKSPACE_ID,
        owner_id=uuid4(),
        agent_id=uuid4(),
        instructions="do it",
        name="t",
        model_id="m",
        reasoning_effort=None,
    )
    svc = TriggerService(AsyncMock(), TEST_WORKSPACE_ID)
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


async def test_run_now_launches_without_an_oauth_gate(monkeypatch):
    svc, trigger, user = _service()
    monkeypatch.setattr(
        triggers_mod,
        "AgentService",
        MagicMock(
            return_value=MagicMock(
                require_permission=AsyncMock(),
                repository=MagicMock(
                    get_scoped=AsyncMock(return_value=MagicMock(is_archived=False))
                ),
            )
        ),
    )
    monkeypatch.setattr(
        triggers_mod, "ThreadService", MagicMock(return_value=svc.thread_service)
    )
    monkeypatch.setattr(
        triggers_mod,
        "RunService",
        MagicMock(
            return_value=MagicMock(
                create=AsyncMock(return_value=SimpleNamespace(id="run1"))
            )
        ),
    )

    result = await svc.run_now(trigger.id, user)

    assert result.thread_id == "th1"
    assert result.run_id == "run1"
