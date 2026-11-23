"""Outbound MCP connections: the one place a FastMCP ``Client`` is built.

Every path that talks to a remote MCP server — the agent runtime
(``app/runtime/toolset.py``), the handshake probes (``connectivity.py``) and the
MCP-app endpoints — gets its client from :func:`build_client`, so the things
auxilia needs on top of the framework defaults are decided once:

* **Client identity.** The client names itself ``auxilia`` (with the backend
  version) instead of the SDK's anonymous ``mcp`` default: in ``initialize``
  on legacy servers, in every request's ``io.modelcontextprotocol/clientInfo``
  on 2026-07-28 ones, where the spec says clients SHOULD send it. Servers use
  it for display, logging and tracing only; it is self-reported and unverified.
* **MCP Apps capability.** Servers gate UI-bearing tools (Metabase's
  ``visualize_query``) behind the client advertising the
  ``io.modelcontextprotocol/ui`` extension during the handshake. The SDK's
  ``advertise()`` does exactly that; it replaced a class-level monkeypatch of
  ``ClientSession.initialize`` that rebuilt private capability assembly.
* **Lenient output validation.** ``ClientSession.call_tool`` validates a
  result's ``structuredContent`` against the tool's ``outputSchema`` and raises
  on mismatch. Some servers (Metabase) declare schemas their own output does
  not satisfy, so the result would die before the model saw it.
  :class:`LenientClientSession` logs instead, installed through FastMCP's
  ``TransportOptions.session_class`` — the hook its own proxy uses to skip the
  same validation.
* **Session termination.** The MCP-app endpoints must *not* ``DELETE`` the
  session on exit: Metabase binds the ``sessionToken`` embedded in the widget
  HTML to the MCP session, so terminating it kills the token before the
  browser uses it. The SDK transport takes ``terminate_on_close``; FastMCP's
  ``StreamableHttpTransport`` does not forward it, hence the small subclass.

The FastMCP client is reentrant and hosts its session in a background task, so
its context manager may be entered and exited from different tasks — the
reason the runtime used to host every session in a dedicated task is gone.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Unpack

import httpx2
from fastmcp.client import Client
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.client.transports.base import SessionKwargs, TransportOptions
from mcp import ClientSession
from mcp.client import advertise
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client
from mcp.types import CallToolResult, Implementation

from app.mcp.client.exceptions import as_oauth_required
from app.mcp.compatibility import MCPCompatibilityQuirk, matching_quirks
from app.version import BACKEND_VERSION


logger = logging.getLogger(__name__)

# FastMCP configures its own logger on import: a RichHandler and
# ``propagate = False``, i.e. its records bypass the application's logging
# setup and go straight to stderr in rich formatting. Hand them back to the
# root logger so they get the same handlers and levels as everything else.
_fastmcp_logger = logging.getLogger("fastmcp")
_fastmcp_logger.handlers.clear()
_fastmcp_logger.propagate = True

# MCP Apps extension identifier and the capability payload a host advertises.
# https://github.com/modelcontextprotocol/ext-apps (spec 2026-01-26).
UI_EXTENSION = "io.modelcontextprotocol/ui"
UI_CAPABILITY = {"mimeTypes": ["text/html;profile=mcp-app"]}

CLIENT_INFO = Implementation(name="auxilia", version=BACKEND_VERSION)


@dataclass(frozen=True)
class ConnectionSpec:
    """Everything needed to reach one MCP server for one user.

    ``headers`` carries an API key as a Bearer header; ``auth`` carries the
    user's OAuth provider (an ``httpx2.Auth``). At most one is set — see
    ``connectivity.resolve_transport_auth``, the single auth dispatch.
    """

    url: str
    headers: dict[str, str] | None = None
    auth: httpx2.Auth | None = None
    quirks: tuple[MCPCompatibilityQuirk, ...] = ()


def _matching_transport_quirks(
    spec: ConnectionSpec,
) -> list[MCPCompatibilityQuirk]:
    return [
        quirk
        for quirk in matching_quirks(spec.quirks, server_url=spec.url)
        if quirk.transport is not None
    ]


def _jsonrpc_success_hook(
    statuses: frozenset[int],
) -> Any:
    async def accept_jsonrpc_success(response: httpx2.Response) -> None:
        if response.status_code not in statuses:
            return
        await response.aread()
        try:
            payload = response.json()
        except ValueError:
            return
        if (
            isinstance(payload, dict)
            and payload.get("jsonrpc") == "2.0"
            and "result" in payload
            and "error" not in payload
        ):
            logger.warning(
                "Treating MCP HTTP %s as success because it contains a "
                "successful JSON-RPC result",
                response.status_code,
            )
            response.status_code = 200

    return accept_jsonrpc_success


def _compatibility_httpx_client_factory(
    statuses: frozenset[int],
) -> Any:
    def factory(
        headers: dict[str, str] | None = None,
        timeout: httpx2.Timeout | None = None,
        auth: httpx2.Auth | None = None,
        **_kwargs: Any,
    ) -> httpx2.AsyncClient:
        client = create_mcp_http_client(headers=headers, timeout=timeout, auth=auth)
        client.event_hooks.setdefault("response", []).append(
            _jsonrpc_success_hook(statuses)
        )
        return client

    return factory


def _transport_headers(spec: ConnectionSpec) -> dict[str, str] | None:
    """Apply endpoint-specific transport features without changing stored URLs."""
    headers = dict(spec.headers or {})
    for quirk in _matching_transport_quirks(spec):
        if quirk.transport is None:
            continue
        for header, configured_values in quirk.transport.header_csv_values.items():
            key = next(
                (name for name in headers if name.lower() == header.lower()),
                header,
            )
            values = {
                value.strip()
                for value in headers.get(key, "").split(",")
                if value.strip()
            }
            values.update(configured_values)
            headers[key] = ",".join(sorted(values))
    return headers or None


class LenientClientSession(ClientSession):
    """A ``ClientSession`` that logs output-schema mismatches instead of raising.

    Upstream raises ``RuntimeError`` when a tool's ``structuredContent`` does
    not match its declared ``outputSchema``, which kills the tool call. We
    would rather hand the result to the model and note the server's mistake.
    """

    async def validate_tool_result(self, name: str, result: CallToolResult) -> None:
        try:
            await super().validate_tool_result(name, result)
        except Exception as exc:  # noqa: BLE001 - intentionally lenient
            logger.warning(
                "Ignoring MCP output validation error for tool %s: %s", name, exc
            )


class RecoveringClient(Client[Any]):
    """Reconnect a dead session while preserving active context-manager holds.

    FastMCP keeps a reference count for reentrant ``async with client`` blocks.
    If the remote session task dies while an outer block remains open, its next
    ``__aenter__`` refuses to reconnect because that count is non-zero. Runtime
    tools deliberately keep one outer hold for the whole agent run, so recover
    that stale state and transfer its logical holds to the replacement session.
    """

    async def _connect(self) -> RecoveringClient:
        retained_holds = 0
        state = self._session_state
        async with state.lock:
            session_task = state.session_task
            needs_session = session_task is None or session_task.done()
            if needs_session and state.nesting_counter > 0:
                retained_holds = state.nesting_counter
                self._reset_session_state(full=True)

        if retained_holds:
            logger.warning(
                "Reconnecting dead MCP session with %s active context hold(s)",
                retained_holds,
            )

        await super()._connect()

        if retained_holds:
            async with state.lock:
                session_task = state.session_task
                if session_task is not None and not session_task.done():
                    state.nesting_counter += retained_holds
        return self


class SessionKeepingTransport(StreamableHttpTransport):
    """``StreamableHttpTransport`` that leaves the session alive on exit.

    Identical to the parent except that the SDK transport is opened with
    ``terminate_on_close=False``: no ``DELETE`` is sent when the context exits,
    and the server expires the session by its own TTL. Only the MCP-app
    endpoints use it (see the module docstring). The body mirrors the parent's
    ``connect_session`` because that method offers no seam for the flag;
    revisit when FastMCP exposes ``terminate_on_close``.
    """

    @asynccontextmanager
    async def connect_session(
        self,
        *,
        transport_options: TransportOptions | None = None,
        **session_kwargs: Unpack[SessionKwargs],
    ) -> AsyncIterator[ClientSession]:
        options = transport_options or TransportOptions()
        timeout: httpx2.Timeout | None = None
        read_timeout_seconds = session_kwargs.get("read_timeout_seconds")
        if read_timeout_seconds is not None:
            timeout = httpx2.Timeout(30.0, read=read_timeout_seconds)
        if self.httpx_client_factory is not None:
            http_client = self.httpx_client_factory(
                headers=dict(self.headers),
                timeout=timeout,
                auth=self.auth,
                follow_redirects=True,
            )  # type: ignore[call-arg]
        else:
            http_client = create_mcp_http_client(
                headers=dict(self.headers), timeout=timeout, auth=self.auth
            )
        self._session_id = None
        http_client.event_hooks.setdefault("response", []).append(
            self._capture_session_id
        )
        # The session context is nested, not folded into the parenthesized
        # `async with`: the streams are bound by the transport context and
        # consumed by the session one, and Codacy's analyzer reads the folded
        # form as "using variable 'read_stream' before assignment".
        async with (  # noqa: SIM117 — nesting is deliberate, see above
            http_client,
            streamable_http_client(
                self.url, http_client=http_client, terminate_on_close=False
            ) as (read_stream, write_stream),
        ):
            async with options.session_class(
                read_stream, write_stream, **session_kwargs
            ) as session:
                yield session


def build_client(spec: ConnectionSpec, *, terminate_on_close: bool = True) -> Client:
    """A disconnected FastMCP ``Client`` for ``spec``, configured for auxilia.

    Connect it with ``async with client:`` — reentrant, so a tool bound to it
    can enter it again while a longer-lived context already holds the session.
    """
    transport_cls: type[StreamableHttpTransport] = (
        StreamableHttpTransport if terminate_on_close else SessionKeepingTransport
    )
    statuses = frozenset(
        status
        for quirk in _matching_transport_quirks(spec)
        if quirk.transport is not None
        for status in quirk.transport.jsonrpc_success_statuses
    )
    httpx_client_factory = (
        _compatibility_httpx_client_factory(statuses) if statuses else None
    )
    transport = transport_cls(
        spec.url,
        headers=_transport_headers(spec),
        auth=spec.auth,
        httpx_client_factory=httpx_client_factory,
    )
    client: Client[Any] = RecoveringClient(
        transport,
        client_info=CLIENT_INFO,
        extensions=[advertise(UI_EXTENSION, UI_CAPABILITY)],
    )
    # FastMCP's own proxy swaps the session class the same way; the attribute
    # is the only way in until `Client` takes transport options directly.
    client._transport_options = TransportOptions(session_class=LenientClientSession)
    return client


@asynccontextmanager
async def open_client(
    spec: ConnectionSpec, *, terminate_on_close: bool = True
) -> AsyncIterator[Client]:
    """Connect to ``spec`` for the duration of the block.

    This is the MCP seam for the per-request paths: a server that needs
    authorization fails with our ``OAuthAuthorizationRequired``, which FastMCP
    reports as the cause of its own "failed to connect" / dead-session error.
    It is unwrapped here so every caller can catch it plainly.

    The ``try`` deliberately covers the caller's body too: servers such as
    Google's answer ``initialize`` unauthenticated and challenge only later
    requests, so the requirement can surface from the caller's
    ``list_tools()`` rather than from the connect. Only an exception that
    *carries* the requirement is rewritten; any other failure from the body
    propagates untouched.
    """
    client = build_client(spec, terminate_on_close=terminate_on_close)
    try:
        async with client:
            yield client
    except BaseException as exc:
        oauth = as_oauth_required(exc)
        if oauth is not None and oauth is not exc:
            raise oauth from exc
        raise
