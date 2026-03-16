from contextlib import asynccontextmanager
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi.testclient import TestClient

from app.mcp.servers.models import MCPAuthType, MCPServerDB


def make_server(**kwargs) -> MCPServerDB:
    defaults = {
        "id": uuid4(),
        "name": "Chart-MCP",
        "url": "http://127.0.0.1:3001/mcp",
        "auth_type": MCPAuthType.none,
        "icon_url": None,
        "description": None,
        "created_at": datetime.now(),
        "updated_at": datetime.now(),
    }
    return MCPServerDB(**{**defaults, **kwargs})


def _mock_server_lookup(mock_db, server: MCPServerDB | None) -> None:
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = server
    mock_db.execute.return_value = mock_result


def test_read_resource_success_returns_response_from_mcp_session(
    client: TestClient, mock_db, admin_user
):
    server = make_server()
    _mock_server_lookup(mock_db, server)

    session = AsyncMock()
    session.read_resource = AsyncMock(
        return_value={"contents": [{"uri": "ui://charts/pie", "mimeType": "text/html"}]}
    )

    connect_call = {}

    def fake_connect(mcp_server, user_id, db):
        connect_call["mcp_server"] = mcp_server
        connect_call["user_id"] = user_id
        connect_call["db"] = db

        @asynccontextmanager
        async def _ctx():
            yield session, []

        return _ctx()

    with patch("app.mcp.apps.router.connect_to_server", side_effect=fake_connect):
        response = client.post(
            f"/mcp-servers/{server.id}/app/read-resource",
            json={"uri": "ui://charts/pie"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "contents": [{"uri": "ui://charts/pie", "mimeType": "text/html"}]
    }
    session.read_resource.assert_awaited_once_with("ui://charts/pie")
    assert connect_call["mcp_server"] == server
    assert connect_call["user_id"] == str(admin_user.id)
    assert connect_call["db"] == mock_db


def test_call_tool_success_returns_response_from_mcp_session(
    client: TestClient, mock_db, admin_user
):
    _ = admin_user
    server = make_server()
    _mock_server_lookup(mock_db, server)

    session = AsyncMock()
    session.call_tool = AsyncMock(
        return_value={
            "content": [{"type": "text", "text": "Rendered chart"}],
            "isError": False,
        }
    )

    def fake_connect(_, __, ___):
        @asynccontextmanager
        async def _ctx():
            yield session, []

        return _ctx()

    with patch("app.mcp.apps.router.connect_to_server", side_effect=fake_connect):
        response = client.post(
            f"/mcp-servers/{server.id}/app/call-tool",
            json={"tool_name": "render_pie_chart", "arguments": {"title": "Q1"}},
        )

    assert response.status_code == 200
    assert response.json() == {
        "content": [{"type": "text", "text": "Rendered chart"}],
        "isError": False,
    }
    session.call_tool.assert_awaited_once_with("render_pie_chart", {"title": "Q1"})


def test_read_resource_requires_authentication(client: TestClient):
    response = client.post(
        f"/mcp-servers/{uuid4()}/app/read-resource",
        json={"uri": "ui://charts/pie"},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Not authenticated"}


def test_read_resource_returns_404_when_server_not_found(
    client: TestClient, mock_db, admin_user
):
    _ = admin_user
    _mock_server_lookup(mock_db, None)

    response = client.post(
        f"/mcp-servers/{uuid4()}/app/read-resource",
        json={"uri": "ui://charts/pie"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "MCP server not found"}


def test_read_resource_invalid_resource_returns_stable_error_payload(
    client: TestClient, mock_db, admin_user
):
    _ = admin_user
    server = make_server()
    _mock_server_lookup(mock_db, server)

    session = AsyncMock()
    session.read_resource = AsyncMock(
        side_effect=ValueError("Unknown resource: ui://charts/missing")
    )

    def fake_connect(_, __, ___):
        @asynccontextmanager
        async def _ctx():
            yield session, []

        return _ctx()

    with patch("app.mcp.apps.router.connect_to_server", side_effect=fake_connect):
        response = client.post(
            f"/mcp-servers/{server.id}/app/read-resource",
            json={"uri": "ui://charts/missing"},
        )

    assert response.status_code == 400
    assert response.json() == {
        "detail": "MCP app read-resource failed: Unknown resource: ui://charts/missing"
    }


def test_call_tool_invalid_tool_returns_stable_error_payload(
    client: TestClient, mock_db, admin_user
):
    _ = admin_user
    server = make_server()
    _mock_server_lookup(mock_db, server)

    session = AsyncMock()
    session.call_tool = AsyncMock(side_effect=ValueError("Unknown tool: export_png"))

    def fake_connect(_, __, ___):
        @asynccontextmanager
        async def _ctx():
            yield session, []

        return _ctx()

    with patch("app.mcp.apps.router.connect_to_server", side_effect=fake_connect):
        response = client.post(
            f"/mcp-servers/{server.id}/app/call-tool",
            json={"tool_name": "export_png", "arguments": {"id": "chart-1"}},
        )

    assert response.status_code == 400
    assert response.json() == {
        "detail": "MCP app call-tool failed: Unknown tool: export_png"
    }
