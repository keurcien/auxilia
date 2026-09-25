"""DELETE /mcp-servers/{id} and its delete-guard listing compose two modules
in the direction they depend — bindings are the agents module's, the server
row is this one's (#369)."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.agents.mcp_servers.service import get_agent_mcp_server_service
from app.exceptions import DomainValidationError, NotFoundError
from app.main import app
from app.mcp.servers.schemas import MCPServerAgentResponse
from app.mcp.servers.service import get_mcp_server_service


@pytest.fixture
def mcp_server_service():
    service = AsyncMock()
    app.dependency_overrides[get_mcp_server_service] = lambda: service
    yield service
    app.dependency_overrides.pop(get_mcp_server_service, None)


@pytest.fixture
def binding_service():
    service = AsyncMock()
    service.list_agents_for_server.return_value = []
    app.dependency_overrides[get_agent_mcp_server_service] = lambda: service
    yield service
    app.dependency_overrides.pop(get_agent_mcp_server_service, None)


def test_list_server_agents_requires_admin(
    client, mcp_server_service, binding_service, current_user
):
    response = client.get(f"/mcp-servers/{uuid4()}/agents")
    assert response.status_code == 403


def test_list_server_agents(client, mcp_server_service, binding_service, admin_user):
    server_id = uuid4()
    agent_id = uuid4()
    binding_service.list_agents_for_server.return_value = [
        MCPServerAgentResponse(id=agent_id, name="Docs Researcher", emoji="📚")
    ]

    response = client.get(f"/mcp-servers/{server_id}/agents")

    assert response.status_code == 200
    [agent] = response.json()
    assert agent["id"] == str(agent_id)
    assert agent["name"] == "Docs Researcher"
    mcp_server_service.get.assert_awaited_once_with(server_id)
    binding_service.list_agents_for_server.assert_awaited_once_with(server_id)


def test_list_server_agents_unknown_server_is_404(
    client, mcp_server_service, binding_service, admin_user
):
    mcp_server_service.get.side_effect = NotFoundError("MCP server not found")

    response = client.get(f"/mcp-servers/{uuid4()}/agents")

    assert response.status_code == 404
    binding_service.list_agents_for_server.assert_not_called()


def test_delete_requires_admin(
    client, mcp_server_service, binding_service, current_user
):
    response = client.delete(f"/mcp-servers/{uuid4()}")
    assert response.status_code == 403
    mcp_server_service.delete.assert_not_called()


def test_delete_without_detach_leaves_bindings_alone(
    client, mcp_server_service, binding_service, admin_user
):
    server_id = uuid4()

    response = client.delete(f"/mcp-servers/{server_id}")

    assert response.status_code == 204
    binding_service.detach_server.assert_not_called()
    mcp_server_service.delete.assert_awaited_once_with(server_id)


def test_delete_in_use_is_refused(
    client, mcp_server_service, binding_service, admin_user
):
    mcp_server_service.delete.side_effect = DomainValidationError(
        "MCP server is used by agents — detach it first"
    )

    response = client.delete(f"/mcp-servers/{uuid4()}")

    assert response.status_code == 400
    assert "detach" in response.json()["detail"]


def test_delete_with_detach_agents_detaches_then_deletes(
    client, mcp_server_service, binding_service, admin_user
):
    server_id = uuid4()
    calls = MagicMock()
    calls.attach_mock(binding_service.detach_server, "detach")
    calls.attach_mock(mcp_server_service.delete, "delete")

    response = client.delete(f"/mcp-servers/{server_id}?detach_agents=true")

    assert response.status_code == 204
    assert [name for name, _, _ in calls.mock_calls] == ["detach", "delete"]
    binding_service.detach_server.assert_awaited_once_with(server_id)
    mcp_server_service.delete.assert_awaited_once_with(server_id)
