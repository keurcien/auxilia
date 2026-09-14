"""The MCP client stack against a real MCP server over Streamable HTTP.

Every other MCP test in this suite talks to duck-typed fakes, which pass
whatever the SDK does. These run an in-process `MCPServer` (MCP SDK v2) under
uvicorn and drive it through the same FastMCP client, `langchain.mcp` adapter
and `Toolset` the runtime uses, so a framework upgrade that changes the
handshake, the tool shapes or the error surface fails here first.
"""

from __future__ import annotations

import asyncio
import socket
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import anyio
import httpx2
import pytest
import uvicorn
from fastapi.encoders import jsonable_encoder
from langchain_core.messages import ToolMessage
from mcp import ClientSession
from mcp.server.mcpserver import Context, MCPServer
from mcp.types import CallToolResult

from app.agents.toolset import PreparedToolset, Toolset
from app.mcp.client.connection import (
    UI_EXTENSION,
    ConnectionSpec,
    LenientClientSession,
    build_client,
    open_client,
)
from app.mcp.client.exceptions import OAuthAuthorizationRequired


AUTH_URL = "https://auth.example/authorize?client_id=abc"
WIDGET_URI = "ui://widget"


def _build_server() -> MCPServer:
    server = MCPServer("live-test")

    @server.tool()
    def echo(text: str) -> str:
        return text

    @server.tool()
    def fail() -> str:
        raise ValueError("the server says no")

    @server.tool(meta={"ui": {"resourceUri": WIDGET_URI}})
    def widget() -> dict[str, Any]:
        return {"rows": [1, 2, 3]}

    @server.tool()
    def advertised_extensions(ctx: Context) -> dict[str, Any]:
        """What the client advertised under `capabilities.extensions`."""
        capabilities = ctx.client_capabilities
        return dict(capabilities.extensions or {}) if capabilities else {}

    @server.resource(WIDGET_URI, mime_type="text/html;profile=mcp-app")
    def widget_html() -> str:
        return "<html>widget</html>"

    return server


class _MethodCounter:
    """ASGI middleware counting requests per HTTP method."""

    def __init__(self, app):
        self.app = app
        self.counts: dict[str, int] = {}

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            method = scope["method"]
            self.counts[method] = self.counts.get(method, 0) + 1
        await self.app(scope, receive, send)


@dataclass
class LiveServer:
    url: str
    counter: _MethodCounter


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
async def live_server() -> AsyncIterator[LiveServer]:
    mcp_server = _build_server()
    counter = _MethodCounter(mcp_server.streamable_http_app(json_response=True))
    port = _free_port()
    config = uvicorn.Config(
        counter, host="127.0.0.1", port=port, log_level="warning", lifespan="on"
    )
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    while not server.started:
        if task.done():
            task.result()
        await asyncio.sleep(0.01)
    try:
        yield LiveServer(url=f"http://127.0.0.1:{port}/mcp", counter=counter)
    finally:
        server.should_exit = True
        await task


class _NeedsAuthorization(httpx2.Auth):
    """An auth hook whose flow ends where ours does: the user must go elsewhere."""

    async def async_auth_flow(self, request):
        raise OAuthAuthorizationRequired(AUTH_URL)
        yield request  # pragma: no cover — keeps this an async generator


# ---------------------------------------------------------------------------
# open_client — the per-request path
# ---------------------------------------------------------------------------


async def test_open_client_lists_tools_and_advertises_the_ui_extension(live_server):
    async with open_client(ConnectionSpec(url=live_server.url)) as client:
        names = sorted(tool.name for tool in await client.list_tools())
        result = await client.call_tool("advertised_extensions")

    assert names == ["advertised_extensions", "echo", "fail", "widget"]
    assert UI_EXTENSION in result.data


async def test_the_legacy_handshake_also_advertises_the_ui_extension(live_server):
    """Metabase-era servers negotiate with `initialize`; the capability has to
    ride that request too, not only `server/discover`."""
    client = build_client(ConnectionSpec(url=live_server.url))
    client.mode = "legacy"
    async with client:
        assert client.initialize_result is not None
        result = await client.call_tool("advertised_extensions")

    assert UI_EXTENSION in result.data


async def test_a_server_that_needs_authorization_surfaces_plainly(live_server):
    """FastMCP reports a connect failure as its own RuntimeError with the real
    cause chained; the seam must hand callers the requirement itself."""
    spec = ConnectionSpec(url=live_server.url, auth=_NeedsAuthorization())

    with pytest.raises(OAuthAuthorizationRequired) as exc_info:
        async with open_client(spec):
            pass  # pragma: no cover

    assert exc_info.value.url == AUTH_URL


async def test_the_session_keeping_transport_sends_no_delete(live_server):
    """MCP-app requests leave the session to expire by TTL (Metabase binds the
    widget's token to it); every other path terminates it."""
    for terminate_on_close in (True, False):
        live_server.counter.counts.clear()
        client = build_client(
            ConnectionSpec(url=live_server.url), terminate_on_close=terminate_on_close
        )
        client.mode = "legacy"  # the modern era has no session to terminate
        async with client:
            await client.list_tools()
        assert live_server.counter.counts.get("DELETE", 0) == int(terminate_on_close)


async def test_an_mcp_app_resource_serializes_in_wire_case(live_server):
    """The MCP-app endpoints return the SDK result as-is; the frontend reads
    the camelCase wire names, which v2's snake_case fields alias to."""
    async with open_client(ConnectionSpec(url=live_server.url)) as client:
        result = await client.read_resource_mcp(WIDGET_URI)

    encoded = jsonable_encoder(result)
    assert encoded["contents"][0]["mimeType"] == "text/html;profile=mcp-app"
    assert encoded["contents"][0]["text"] == "<html>widget</html>"


async def test_build_client_wires_the_lenient_session_into_the_connection(live_server):
    """`LenientClientSession` reaches the wire only if FastMCP honours the
    `_transport_options` hook `build_client` sets; assert on the live session
    rather than trust the private attribute."""
    async with open_client(ConnectionSpec(url=live_server.url)) as client:
        assert isinstance(client.session, LenientClientSession)

    client = build_client(ConnectionSpec(url=live_server.url), terminate_on_close=False)
    async with client:
        assert isinstance(client.session, LenientClientSession)


async def test_the_lenient_session_logs_instead_of_raising(caplog):
    schema = {"type": "object", "properties": {"a": {"type": "integer"}}}
    result = CallToolResult(content=[], structured_content={"a": "not-an-int"})

    def streams():
        send, receive = anyio.create_memory_object_stream[object](0)
        return receive, send

    strict = ClientSession(*streams())
    strict._tool_output_schemas["t"] = schema
    with pytest.raises(RuntimeError):
        await strict.validate_tool_result("t", result)

    lenient = LenientClientSession(*streams())
    lenient._tool_output_schemas["t"] = schema
    await lenient.validate_tool_result("t", result)
    assert "Ignoring MCP output validation error" in caplog.text


# ---------------------------------------------------------------------------
# Toolset.open — the run path
# ---------------------------------------------------------------------------


def _prepared(url: str, **connections: ConnectionSpec) -> PreparedToolset:
    settings = {
        "echo": "always_allow",
        "fail": "needs_approval",
        "widget": "always_allow",
        "advertised_extensions": "disabled",
    }
    connections = connections or {"alpha": ConnectionSpec(url=url)}
    return PreparedToolset(
        connections=connections,
        tool_settings=dict.fromkeys(connections, settings),
        server_id_by_name={name: f"id-{name}" for name in connections},
        interrupt_on={f"{name}_fail": True for name in connections},
        apply_ui=True,
    )


async def _call(tool, **args) -> ToolMessage:
    return await tool.ainvoke(
        {"name": tool.name, "args": args, "id": "call-1", "type": "tool_call"}
    )


async def test_toolset_open_binds_namespaced_tools_from_every_server(live_server):
    prepared = _prepared(
        live_server.url,
        alpha=ConnectionSpec(url=live_server.url),
        beta=ConnectionSpec(url=live_server.url),
    )

    async with Toolset.open(prepared) as toolset:
        by_name = {tool.name: tool for tool in toolset.all}
        # `{server}_{tool}`, filtered by the persisted settings, disabled ones gone.
        assert sorted(by_name) == [
            "alpha_echo",
            "alpha_fail",
            "alpha_widget",
            "beta_echo",
            "beta_fail",
            "beta_widget",
        ]
        assert toolset.interrupt_on == {"alpha_fail": True, "beta_fail": True}

        echoed = await _call(by_name["beta_echo"], text="hello")
        assert echoed.status == "success"
        assert [block["text"] for block in echoed.content] == ["hello"]
        # A plain tool's structured content never reaches the artifact.
        assert echoed.artifact is None

        # `isError=True` reaches the model as a failed ToolMessage carrying the
        # server's own text (MCPServer masks unexpected exceptions generically).
        failed = await _call(by_name["alpha_fail"])
        assert failed.status == "error"
        assert [block["text"] for block in failed.content] == [
            "Error executing tool fail"
        ]

        # App tools are recognised from the server's `_meta` and their artifact
        # is kept whole and stamped for the widget frontend.
        widget = await _call(by_name["alpha_widget"])
        assert widget.artifact == {
            "structured_content": {"rows": [1, 2, 3]},
            "mcp_app_resource_uri": WIDGET_URI,
            "mcp_server_id": "id-alpha",
        }


async def test_toolset_open_unwraps_a_servers_authorization_requirement(live_server):
    prepared = _prepared(
        live_server.url,
        alpha=ConnectionSpec(url=live_server.url),
        beta=ConnectionSpec(url=live_server.url, auth=_NeedsAuthorization()),
    )

    with pytest.raises(OAuthAuthorizationRequired) as exc_info:
        async with Toolset.open(prepared):
            pass  # pragma: no cover

    assert exc_info.value.url == AUTH_URL
