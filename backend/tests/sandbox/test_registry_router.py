from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.agents.core.service import get_agent_service
from app.main import app
from app.sandbox.models import SandboxProviderType
from app.sandbox.schemas import (
    SandboxResponse,
    SandboxSecretHint,
)
from app.sandbox.service import get_sandbox_service


@pytest.fixture
def sandbox_service():
    service = AsyncMock()
    app.dependency_overrides[get_sandbox_service] = lambda: service
    yield service
    app.dependency_overrides.pop(get_sandbox_service, None)


@pytest.fixture
def agent_service():
    """The agents side of the delete guard, composed by the router."""
    service = AsyncMock()
    service.list_for_sandbox.return_value = []
    app.dependency_overrides[get_agent_service] = lambda: service
    yield service
    app.dependency_overrides.pop(get_agent_service, None)


def _response(**overrides) -> SandboxResponse:
    now = datetime.now(UTC)
    defaults = {
        "id": uuid4(),
        "name": "Data lab",
        "description": None,
        "provider": SandboxProviderType.cloudrun,
        "url": "https://gateway.run.app",
        "config": {"allow_egress": False},
        "has_secret": True,
        "created_at": now,
        "updated_at": now,
    }
    return SandboxResponse(**{**defaults, **overrides})


def test_list_is_available_to_any_user(client, sandbox_service, current_user):
    sandbox_service.list_responses.return_value = [_response()]

    response = client.get("/sandboxes/")

    assert response.status_code == 200
    body = response.json()
    assert body[0]["name"] == "Data lab"
    assert body[0]["has_secret"] is True
    assert "encrypted_secret" not in body[0]


def test_create_requires_admin(client, sandbox_service, current_user):
    response = client.post(
        "/sandboxes/",
        json={"name": "X", "provider": "opensandbox", "url": "sbx.example.com"},
    )
    assert response.status_code == 403


def test_create_passes_the_payload_through(client, sandbox_service, admin_user):
    sandbox_service.create.return_value = _response(
        provider=SandboxProviderType.opensandbox, url="sbx.example.com"
    )

    response = client.post(
        "/sandboxes/",
        json={
            "name": "Python VM",
            "provider": "opensandbox",
            "url": "sbx.example.com",
            "secret": "sk-secret",
            "config": {"default_image": "python:3.13"},
        },
    )

    assert response.status_code == 201
    sandbox_service.create.assert_awaited_once()
    payload = sandbox_service.create.await_args.args[0]
    assert payload.name == "Python VM"
    assert payload.secret == "sk-secret"
    assert payload.config == {"default_image": "python:3.13"}


def test_secret_hint_requires_admin(client, sandbox_service, current_user):
    response = client.get(f"/sandboxes/{uuid4()}/secret-hint")
    assert response.status_code == 403


def test_secret_hint_for_admin(client, sandbox_service, admin_user):
    sandbox_service.get_secret_hint.return_value = SandboxSecretHint(
        is_set=True, last4="1234", length=32
    )

    response = client.get(f"/sandboxes/{uuid4()}/secret-hint")

    assert response.status_code == 200
    assert response.json() == {"is_set": True, "last4": "1234", "length": 32}


def test_patch_passes_through(client, sandbox_service, admin_user):
    sandbox_service.update.return_value = _response(name="Renamed lab")
    sandbox_id = uuid4()

    response = client.patch(f"/sandboxes/{sandbox_id}", json={"name": "Renamed lab"})

    assert response.status_code == 200
    assert response.json()["name"] == "Renamed lab"
    args = sandbox_service.update.await_args.args
    assert args[0] == sandbox_id
    assert args[1].name == "Renamed lab"


def test_delete_returns_204(client, sandbox_service, agent_service, admin_user):
    sandbox_id = uuid4()

    response = client.delete(f"/sandboxes/{sandbox_id}")

    assert response.status_code == 204
    # The agents module gets to refuse first; then the row goes.
    agent_service.release_sandbox.assert_awaited_once_with(
        sandbox_id, detach_agents=False
    )
    sandbox_service.delete.assert_awaited_once_with(sandbox_id)


def test_list_sandbox_agents_requires_admin(client, sandbox_service, current_user):
    response = client.get(f"/sandboxes/{uuid4()}/agents")
    assert response.status_code == 403


def test_list_sandbox_agents(client, sandbox_service, agent_service, admin_user):
    from types import SimpleNamespace

    agent_id = uuid4()
    agent_service.list_for_sandbox.return_value = [
        SimpleNamespace(id=agent_id, name="Python developer", emoji="🐍", color=None)
    ]

    response = client.get(f"/sandboxes/{uuid4()}/agents")

    assert response.status_code == 200
    [agent] = response.json()
    assert agent["id"] == str(agent_id)
    assert agent["name"] == "Python developer"
    sandbox_service.get_or_404.assert_awaited_once()  # 404 before the bindings


def test_delete_in_use_is_refused(client, sandbox_service, agent_service, admin_user):
    from app.exceptions import DomainValidationError

    agent_service.release_sandbox.side_effect = DomainValidationError(
        "Sandbox is used by 2 agent(s) — detach it first"
    )

    response = client.delete(f"/sandboxes/{uuid4()}")

    assert response.status_code == 400
    assert "detach" in response.json()["detail"]
    sandbox_service.delete.assert_not_awaited()


def test_delete_with_detach_agents_passes_the_flag(
    client, sandbox_service, agent_service, admin_user
):
    sandbox_id = uuid4()

    response = client.delete(f"/sandboxes/{sandbox_id}?detach_agents=true")

    assert response.status_code == 204
    agent_service.release_sandbox.assert_awaited_once_with(
        sandbox_id, detach_agents=True
    )
    sandbox_service.delete.assert_awaited_once_with(sandbox_id)
