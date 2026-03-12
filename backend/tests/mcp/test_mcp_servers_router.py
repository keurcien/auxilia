from datetime import datetime
from unittest.mock import MagicMock
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

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


def test_create_mcp_server_duplicate_url_returns_409(
    client: TestClient, mock_db, admin_user
):
    _ = admin_user
    server_data = {
        "name": "Chart-MCP",
        "url": "http://127.0.0.1:3001/mcp",
        "auth_type": "none",
    }
    mock_db.flush.side_effect = IntegrityError(
        "INSERT INTO mcp_servers (...) VALUES (...)",
        {"url": server_data["url"]},
        Exception(
            'duplicate key value violates unique constraint "uq_mcp_servers_url"'
        ),
    )

    response = client.post("/mcp-servers/", json=server_data)

    assert response.status_code == 409
    assert response.json()["detail"] == "MCP server URL already exists"
    mock_db.rollback.assert_awaited_once()


def test_delete_mcp_server_attached_to_agent_returns_409(
    client: TestClient, mock_db, admin_user
):
    _ = admin_user
    server = make_server()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = server
    mock_db.execute.return_value = mock_result
    mock_db.commit.side_effect = IntegrityError(
        "DELETE FROM mcp_servers WHERE id = ...",
        {"id": str(server.id)},
        Exception(
            'update or delete on table "mcp_servers" violates foreign key constraint '
            '"agent_mcp_server_bindings_mcp_server_id_fkey" on table "agent_mcp_server_bindings"'
        ),
    )

    response = client.delete(f"/mcp-servers/{server.id}")

    assert response.status_code == 409
    assert response.json()["detail"] == "MCP server is attached to one or more agents"
    mock_db.rollback.assert_awaited_once()
