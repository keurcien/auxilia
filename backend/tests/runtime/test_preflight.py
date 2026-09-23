"""`preflight.required_oauth_url` — the OAuth gate `launch` and the worker share.

Tested directly (not via an endpoint) because it resolves agents and MCP
servers, whose Postgres-only tables the SQLite `run_db` fixture doesn't create.
"""

from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx

from app.mcp.client.exceptions import OAuthAuthorizationRequired
from app.mcp.servers.models import MCPAuthType
from app.runtime.preflight import required_oauth_url


def _binding(server_id):
    b = MagicMock()
    b.mcp_server_id = server_id
    return b


async def _run_gate(*, auth_type, probe_result, initiate=None, spec=None):
    """Drive the gate with one bound server. Returns the collaborator mocks
    plus the gate's answer (`auth_url`: the URL a launch needs, or None)."""
    server = MagicMock()
    server.id = uuid4()
    server.auth_type = auth_type

    read_spec = SimpleNamespace(all_mcp_bindings=[_binding(server.id)])
    repository = MagicMock(get_run_spec=AsyncMock(return_value=read_spec))
    probe = AsyncMock(return_value=probe_result)
    initiate_oauth = initiate or AsyncMock()
    db = AsyncMock()
    db.execute.return_value = MagicMock(
        scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[server])))
    )

    with ExitStack() as stack:
        stack.enter_context(
            patch("app.runtime.preflight.AgentRepository", return_value=repository)
        )
        stack.enter_context(
            patch("app.mcp.client.connectivity.is_authorized", new=probe)
        )
        stack.enter_context(
            patch("app.runtime.preflight.initiate_oauth", new=initiate_oauth)
        )
        auth_url = await required_oauth_url(db, uuid4(), "user-1", spec=spec)
    return SimpleNamespace(
        server=server,
        probe=probe,
        initiate=initiate_oauth,
        db=db,
        repository=repository,
        auth_url=auth_url,
    )


async def test_gate_returns_the_auth_url_when_oauth_server_unauthorized():
    """The URL is a return value, not an exception: each caller decides what
    to do with it (401, a failed background run, a rejected trigger)."""
    initiate = AsyncMock(side_effect=OAuthAuthorizationRequired("https://auth.example"))
    gate = await _run_gate(
        auth_type=MCPAuthType.oauth2, probe_result=False, initiate=initiate
    )

    assert gate.auth_url == "https://auth.example"
    # Args matter: probing the wrong user (or swapped args) would authorize
    # against the wrong identity.
    initiate.assert_awaited_once()
    server = initiate.await_args.args[0]
    assert initiate.await_args.args[:2] == (server, "user-1")
    assert server.auth_type == MCPAuthType.oauth2


async def test_gate_passes_when_authorized():
    gate = await _run_gate(auth_type=MCPAuthType.oauth2, probe_result=True)
    assert gate.auth_url is None
    gate.probe.assert_awaited_once_with(gate.server, "user-1")
    gate.initiate.assert_not_awaited()
    # The gate releases the request connection before its network IO.
    gate.db.commit.assert_awaited_once()


async def test_gate_ignores_non_oauth_servers():
    # api_key/none are always authorized — never probed, never gated.
    gate = await _run_gate(auth_type=MCPAuthType.api_key, probe_result=False)
    assert gate.auth_url is None
    gate.probe.assert_not_awaited()
    gate.initiate.assert_not_awaited()


async def test_gate_fails_open_on_oauth_infra_errors():
    # Provider down during discovery must not block the launch — the run
    # proceeds and the failure surfaces in-thread, as before the gate existed.
    initiate = AsyncMock(side_effect=httpx.ConnectError("host down"))
    gate = await _run_gate(
        auth_type=MCPAuthType.oauth2, probe_result=False, initiate=initiate
    )
    assert gate.auth_url is None
    gate.initiate.assert_awaited_once_with(gate.server, "user-1", gate.db)


async def test_gate_uses_the_spec_it_is_handed_instead_of_reading_again():
    """`launch` already read the graph for the availability gates; handing it
    over keeps the launch at one `get_run_spec`."""
    gate = await _run_gate(
        auth_type=MCPAuthType.oauth2,
        probe_result=True,
        spec=SimpleNamespace(all_mcp_bindings=[_binding(uuid4())]),
    )
    assert gate.auth_url is None
    gate.repository.get_run_spec.assert_not_awaited()


async def test_gate_passes_an_agent_with_no_bindings_without_touching_servers():
    db = AsyncMock()
    with patch("app.runtime.preflight.AgentRepository") as repo_cls:
        repo_cls.return_value.get_run_spec = AsyncMock(return_value=None)
        assert await required_oauth_url(db, uuid4(), "user-1") is None
    db.execute.assert_not_awaited()
    db.commit.assert_not_awaited()
