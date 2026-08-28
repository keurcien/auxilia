"""TriggerService.claim_and_enqueue — the scanner tick.

Covers the ordering constraint from design review §3.7: the model whitelist must
be warmed *before* the claim transaction opens.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

import app.triggers.service as triggers_mod
from app.triggers.service import TriggerService


@pytest.fixture
def service(monkeypatch) -> TriggerService:
    svc = TriggerService(AsyncMock())
    svc.repository = MagicMock(claim_due=AsyncMock(return_value=[]))
    svc.model_service = AsyncMock()
    monkeypatch.setattr(triggers_mod, "RunService", MagicMock())
    return svc


async def test_warms_the_whitelist_before_opening_the_claim_transaction(
    service, monkeypatch
):
    """`claim_due` takes `FOR UPDATE SKIP LOCKED` locks on every trigger it
    claims, and `is_available` runs inside that transaction. On a cold or
    expired catalog cache that check is a multi-second CDN fetch — held open
    across those row locks unless the cache is warmed first."""
    calls = MagicMock()
    warm = AsyncMock()
    calls.attach_mock(warm, "warm")
    calls.attach_mock(service.repository.claim_due, "claim")
    monkeypatch.setattr(triggers_mod.ModelService, "list_whitelisted", warm)

    await service.claim_and_enqueue()

    ordered = [name for name, _, _ in calls.mock_calls]
    assert ordered.index("warm") < ordered.index("claim")


async def test_a_tick_with_nothing_due_enqueues_nothing(service, monkeypatch):
    monkeypatch.setattr(triggers_mod.ModelService, "list_whitelisted", AsyncMock())

    assert await service.claim_and_enqueue() == []
