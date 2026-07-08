"""RunService.ensure_mcp_authorized — the pre-flight OAuth gate.

Tested directly (not via an endpoint) because it resolves agents and MCP
servers, whose Postgres-only tables the SQLite `run_db` fixture doesn't create.
"""

from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.agents.runs.service import RunService
from app.mcp.client.exceptions import OAuthAuthorizationRequired
from app.mcp.servers.models import MCPAuthType


def _binding(server_id):
    b = MagicMock()
    b.mcp_server_id = server_id
    return b


async def _run_gate(*, auth_type, probe_result, initiate=None):
    """Drive the gate with one bound server. Returns the MCPServerService mock."""
    server = MagicMock()
    server.id = uuid4()
    server.auth_type = auth_type

    agent_service = MagicMock(
        collect_run_bindings=AsyncMock(return_value=[_binding(server.id)])
    )
    server_repo = MagicMock(get=AsyncMock(return_value=server))
    server_service = MagicMock(initiate_oauth=initiate or AsyncMock())

    with ExitStack() as stack:
        stack.enter_context(
            patch("app.agents.core.service.AgentService", return_value=agent_service)
        )
        stack.enter_context(
            patch(
                "app.mcp.servers.repository.MCPServerRepository",
                return_value=server_repo,
            )
        )
        stack.enter_context(
            patch(
                "app.mcp.servers.service.MCPServerService", return_value=server_service
            )
        )
        stack.enter_context(
            patch(
                "app.mcp.utils.probe_mcp_server",
                new=AsyncMock(return_value=probe_result),
            )
        )
        await RunService(redis=MagicMock()).ensure_mcp_authorized(
            AsyncMock(), uuid4(), "user-1"
        )
    return server_service


async def test_gate_raises_when_oauth_server_unauthorized():
    initiate = AsyncMock(side_effect=OAuthAuthorizationRequired("https://auth.example"))
    with pytest.raises(OAuthAuthorizationRequired):
        await _run_gate(
            auth_type=MCPAuthType.oauth2, probe_result=False, initiate=initiate
        )
    initiate.assert_awaited_once()


async def test_gate_passes_when_authorized():
    svc = await _run_gate(auth_type=MCPAuthType.oauth2, probe_result=True)
    svc.initiate_oauth.assert_not_awaited()


async def test_gate_ignores_non_oauth_servers():
    # api_key/none are always authorized — never probed, never gated.
    svc = await _run_gate(auth_type=MCPAuthType.api_key, probe_result=False)
    svc.initiate_oauth.assert_not_awaited()
