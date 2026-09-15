"""Outbound MCP connections: the one place a FastMCP ``Client`` is built.

Every path that talks to a remote MCP server — the agent runtime
(``app/agents/toolset.py``), the handshake probes (``connectivity.py``) and the
MCP-app endpoints — gets its client from :func:`build_client`, so the three
things auxilia needs on top of the framework defaults are decided once:

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
from typing import Any

import httpx2
from fastmcp.client import Client
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.client.transports.base import SessionKwargs, TransportOptions
from mcp import ClientSession
from mcp.client import advertise
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client
from mcp.types import CallToolResult
from typing_extensions import Unpack

from app.mcp.client.exceptions import as_oauth_required


logger = logging.getLogger(__name__)

# FastMCP configures its own logger on import: a RichHandler and
# ``propagate = False``, i.e. its records bypass the application's logging
# setup and go straight to stderr in rich formatting. Hand them back to the
# root logger so they get the same handlers and levels as everything else.
_fastmcp_logger = logging.getLogger("fastmcp")
_fastmcp_logger.handlers.clear()
_fastmcp_logger.propagate = True


async def _log_non_2xx_body(response: httpx2.Response) -> None:
    """Log a remote MCP server's own error text on a non-2xx response.

    The MCP SDK reads a non-2xx body that isn't a JSON-RPC error, discards it,
    and hands back a generic ``ErrorData("Server returned an error response")``,
    so the real message — e.g. the intermittent HTTP 400 the Google BigQuery MCP
    endpoint returns on ``execute_sql`` — never reaches the logs or the model.
    Log it here instead.

    At DEBUG, not WARNING: an error body can echo request content — a rejected
    ``execute_sql`` may quote the query, its table/column names, even literal
    values — so it must not land in steady-state logs. Raise LOG_LEVEL to DEBUG
    to capture it. 2xx is the success path; 401 is the routine "needs
    authorization" the OAuth flow handles — both are skipped.
    """
    if 200 <= response.status_code < 300 or response.status_code == 401:
        return
    try:
        body = await response.aread()
    except Exception:  # noqa: BLE001 — best-effort diagnostic, never fatal
        return
    logger.debug(
        "MCP %s %s -> HTTP %s: %s",
        response.request.method,
        response.request.url,
        response.status_code,
        body.decode("utf-8", "replace")[:800],
    )


def _logging_http_client_factory(
    *,
    headers: dict[str, str] | None = None,
    auth: httpx2.Auth | None = None,
    timeout: Any = None,
    **_kwargs: Any,
) -> httpx2.AsyncClient:
    """``create_mcp_http_client`` plus the non-2xx body logger, as the factory the
    transport builds its client from (see :func:`build_client`). Extra kwargs are
    accepted and ignored so a future FastMCP that passes more never breaks the one
    seam every MCP path uses; ``timeout`` stays untyped because FastMCP may hand it
    as a float or an ``httpx2.Timeout``."""
    client = create_mcp_http_client(headers=headers, timeout=timeout, auth=auth)
    client.event_hooks.setdefault("response", []).append(_log_non_2xx_body)
    return client


# MCP Apps extension identifier and the capability payload a host advertises.
# https://github.com/modelcontextprotocol/ext-apps (spec 2026-01-26).
UI_EXTENSION = "io.modelcontextprotocol/ui"
UI_CAPABILITY = {"mimeTypes": ["text/html;profile=mcp-app"]}


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
        http_client = create_mcp_http_client(
            headers=dict(self.headers), timeout=timeout, auth=self.auth
        )
        self._session_id = None
        http_client.event_hooks.setdefault("response", []).append(
            self._capture_session_id
        )
        # SessionKeepingTransport builds its own client (it does not go through
        # `httpx_client_factory`), so attach the non-2xx body logger here too.
        http_client.event_hooks["response"].append(_log_non_2xx_body)
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
    transport = transport_cls(
        spec.url,
        headers=spec.headers,
        auth=spec.auth,
        # The base transport builds its httpx client from this factory, so the
        # runtime path (default transport) logs the server's own error body on a
        # non-2xx — the detail the SDK otherwise drops. SessionKeepingTransport
        # ignores the factory and attaches the same hook itself.
        httpx_client_factory=_logging_http_client_factory,
    )
    client: Client[Any] = Client(
        transport, extensions=[advertise(UI_EXTENSION, UI_CAPABILITY)]
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
