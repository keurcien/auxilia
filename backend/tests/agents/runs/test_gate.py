"""RunService.ensure_mcp_authorized — the pre-flight OAuth gate.

Tested directly (not via an endpoint) because it resolves agents and MCP
servers, whose Postgres-only tables the SQLite `run_db` fixture doesn't create.
"""

from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import pytest

from app.agents.runs.service import RunService
from app.mcp.client.exceptions import OAuthAuthorizationRequired
from app.mcp.servers.models import MCPAuthType


def _binding(server_id):
    b = MagicMock()
    b.mcp_server_id = server_id
    return b


async def _run_gate(*, auth_type, probe_result, initiate=None):
    """Drive the gate with one bound server. Returns the collaborator mocks."""
    server = MagicMock()
    server.id = uuid4()
    server.auth_type = auth_type

    agent_service = MagicMock(
        collect_run_bindings=AsyncMock(return_value=[_binding(server.id)])
    )
    server_service = MagicMock(initiate_oauth=initiate or AsyncMock())
    probe = AsyncMock(return_value=probe_result)
    db = AsyncMock()
    db.execute.return_value = MagicMock(
        scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[server])))
    )

    with ExitStack() as stack:
        stack.enter_context(
            patch("app.agents.core.service.AgentService", return_value=agent_service)
        )
        stack.enter_context(
            patch(
                "app.mcp.servers.service.MCPServerService", return_value=server_service
            )
        )
        stack.enter_context(patch("app.mcp.utils.probe_mcp_server", new=probe))
        await RunService(redis=MagicMock()).ensure_mcp_authorized(db, uuid4(), "user-1")
    return SimpleNamespace(
        server=server, probe=probe, server_service=server_service, db=db
    )


async def test_gate_raises_when_oauth_server_unauthorized():
    initiate = AsyncMock(side_effect=OAuthAuthorizationRequired("https://auth.example"))
    with pytest.raises(OAuthAuthorizationRequired):
        await _run_gate(
            auth_type=MCPAuthType.oauth2, probe_result=False, initiate=initiate
        )
    # Args matter: probing the wrong user (or swapped args) would authorize
    # against the wrong identity.
    initiate.assert_awaited_once()
    server = initiate.await_args.args[0]
    assert initiate.await_args.args == (server, "user-1")
    assert server.auth_type == MCPAuthType.oauth2


async def test_gate_passes_when_authorized():
    gate = await _run_gate(auth_type=MCPAuthType.oauth2, probe_result=True)
    gate.probe.assert_awaited_once_with(gate.server, "user-1")
    gate.server_service.initiate_oauth.assert_not_awaited()
    # The gate releases the request connection before its network IO.
    gate.db.commit.assert_awaited_once()


async def test_gate_ignores_non_oauth_servers():
    # api_key/none are always authorized — never probed, never gated.
    gate = await _run_gate(auth_type=MCPAuthType.api_key, probe_result=False)
    gate.probe.assert_not_awaited()
    gate.server_service.initiate_oauth.assert_not_awaited()


async def test_gate_fails_open_on_oauth_infra_errors():
    # Provider down during discovery must not block the launch — the run
    # proceeds and the failure surfaces in-thread, as before the gate existed.
    initiate = AsyncMock(side_effect=httpx.ConnectError("host down"))
    gate = await _run_gate(
        auth_type=MCPAuthType.oauth2, probe_result=False, initiate=initiate
    )
    gate.server_service.initiate_oauth.assert_awaited_once_with(gate.server, "user-1")
