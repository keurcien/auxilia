"""Open MCP SDK v2 ``Client`` connections for auxilia.

This is the single construction point for outbound MCP connections, replacing
both ``langchain_mcp_adapters.client.MultiServerMCPClient`` (session factory)
and the v1 ``ClientSession`` monkeypatches (``app/mcp/client/initialize.py``):

* **MCP Apps capability** — servers gate UI-bearing tools (e.g. Metabase's
  ``visualize_query``) behind the client advertising the
  ``io.modelcontextprotocol/ui`` extension during the handshake. v2 supports
  extension capability ads natively (``Client(extensions=[advertise(...)])``),
  so the v1 ``initialize`` monkeypatch is gone.
* **Lenient output validation** — ``ClientSession.call_tool`` validates a
  result's ``structured_content`` against the tool's ``output_schema`` and
  raises on mismatch. Some servers (Metabase) declare schemas their own output
  doesn't satisfy, so the result would die before reaching the model.
  ``validate_tool_result`` is public in v2; :func:`_make_validation_lenient`
  shadows it per-instance to log instead of raise.

The transport (``streamable_http_client``) is still built on anyio task
groups, so a connection's context manager must be entered and exited in the
same task — same rule as v1; ``app/agents/toolset.py`` hosts each connection
in a dedicated task for that reason.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, TypedDict

import httpx2
from mcp.client.client import Client
from mcp.client.extension import advertise
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp_types import CallToolResult


logger = logging.getLogger(__name__)

# MCP Apps extension identifier and the capability payload a host advertises.
# https://github.com/modelcontextprotocol/ext-apps (spec 2026-01-26).
UI_EXTENSION = "io.modelcontextprotocol/ui"
UI_CAPABILITY = {"mimeTypes": ["text/html;profile=mcp-app"]}


class MCPConnectionSpec(TypedDict, total=False):
    """Connection parameters for one MCP server (built by MCPClientConfigFactory)."""

    url: str
    headers: dict[str, str]
    auth: Any  # httpx2.Auth — WebOAuthClientProvider for oauth2 servers


def build_http_client(
    *,
    headers: dict[str, str] | None = None,
    auth: httpx2.Auth | None = None,
) -> httpx2.AsyncClient:
    """httpx2 client with MCP-friendly defaults (mirrors the SDK's own:
    follow redirects, 30s connect/write/pool, 300s read for SSE streams)."""
    return httpx2.AsyncClient(
        headers=headers,
        auth=auth,
        follow_redirects=True,
        timeout=httpx2.Timeout(30.0, read=300.0),
    )


def _make_validation_lenient(session: ClientSession) -> None:
    """Shadow ``validate_tool_result`` on this session instance so an
    output-schema mismatch is logged and the result still reaches the model."""
    original = session.validate_tool_result

    async def lenient(name: str, result: CallToolResult) -> None:
        try:
            await original(name, result)
        except Exception as exc:  # noqa: BLE001 - intentionally lenient
            logger.warning(
                "Ignoring MCP output validation error for tool %s: %s", name, exc
            )

    session.validate_tool_result = lenient  # type: ignore[method-assign]


@asynccontextmanager
async def open_mcp_client(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    auth: httpx2.Auth | None = None,
    terminate_on_close: bool = True,
) -> AsyncIterator[Client]:
    """Open a connected MCP ``Client`` over Streamable HTTP.

    Args:
        url: The MCP server endpoint.
        headers: Extra headers (e.g. ``Authorization: Bearer`` for api_key auth).
        auth: httpx2 auth hook (``WebOAuthClientProvider`` for oauth2 servers).
        terminate_on_close: When False the session is NOT DELETEd on exit and
            expires by the server's TTL. MCP App paths need this: Metabase binds
            artifacts (the embedded ``sessionToken``) to the MCP session, so
            DELETEing it would kill the token before the browser uses it.

    Must be entered and exited in the same task (anyio cancel-scope ownership
    inside the transport).
    """
    http_client = build_http_client(headers=headers, auth=auth)
    transport = streamable_http_client(
        url, http_client=http_client, terminate_on_close=terminate_on_close
    )
    async with http_client:
        async with Client(
            transport,
            extensions=[advertise(UI_EXTENSION, UI_CAPABILITY)],
            # Response caching off: connections are short-lived (per run/request)
            # and a stale tools/list would defeat the live discovery in Toolset.open.
            cache=None,
        ) as client:
            _make_validation_lenient(client.session)
            yield client


@asynccontextmanager
async def open_mcp_client_from_spec(
    spec: MCPConnectionSpec, *, terminate_on_close: bool = True
) -> AsyncIterator[Client]:
    """Open a client from an ``MCPClientConfigFactory``-built spec dict."""
    async with open_mcp_client(
        spec["url"],
        headers=spec.get("headers"),
        auth=spec.get("auth"),
        terminate_on_close=terminate_on_close,
    ) as client:
        yield client
