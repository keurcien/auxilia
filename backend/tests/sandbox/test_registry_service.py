from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.sandbox.models import SandboxDB, SandboxProviderType
from app.sandbox.schemas import SandboxPatch
from app.sandbox.service import SandboxService


def make_row(**overrides) -> SandboxDB:
    now = datetime.now(UTC)
    defaults = {
        "id": uuid4(),
        "name": "Python VM",
        "description": None,
        "provider": SandboxProviderType.opensandbox,
        "url": "sbx.example.com",
        "config": {
            "default_packages": ["pandas"],
            "timeout": 900,
            "default_image": "python:3.12-slim",
            "volume_mounts": [],
            "use_server_proxy": True,
        },
        "encrypted_secret": None,
        "created_at": now,
        "updated_at": now,
    }
    return SandboxDB(**{**defaults, **overrides})


@pytest.fixture
def service():
    db = AsyncMock()
    db.add = MagicMock()
    svc = SandboxService(db)
    svc.repository = MagicMock()
    svc.repository.get = AsyncMock()
    svc.repository.update = AsyncMock()
    return svc


@pytest.mark.asyncio
async def test_patch_config_overlays_stored_values(service):
    """A partial config patch must not reset omitted fields to defaults —
    the stored config (defaults materialized on write) is the base."""
    row = make_row()
    service.repository.get.return_value = row
    service.repository.update.return_value = row

    await service.update(row.id, SandboxPatch(config={"default_image": "python:3.13"}))

    assert row.config["default_image"] == "python:3.13"
    assert row.config["default_packages"] == ["pandas"]
    assert row.config["timeout"] == 900


@pytest.mark.asyncio
async def test_patch_without_config_keeps_stored_config(service):
    row = make_row()
    service.repository.get.return_value = row
    service.repository.update.return_value = row

    await service.update(row.id, SandboxPatch(name="Renamed"))

    assert row.config["default_image"] == "python:3.12-slim"
    assert row.config["default_packages"] == ["pandas"]
