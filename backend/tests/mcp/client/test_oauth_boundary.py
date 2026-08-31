"""Where "this MCP server needs authorization" is allowed to become a response.

It used to be an app-global exception handler, so *any* endpoint that touched
MCP could answer 401 with an auth URL, and the `ExceptionGroup` registration it
needed (the implicit 401 fires inside anyio task groups) swallowed unrelated
TaskGroup-wrapped exceptions on the way (design review §2.3, §2.4).

Now: the seam unwraps the group, the endpoints whose job is connecting answer
explicitly, and nothing else can.
"""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.exceptions import DomainError, NotFoundError
from app.mcp.client import connectivity
from app.mcp.client.exceptions import OAuthAuthorizationRequired, as_oauth_required
from app.mcp.servers.models import MCPAuthType, MCPServerDB
from app.mcp.servers.schemas import AuthorizationRequired, ToolsListed
from app.mcp.servers.service import MCPServerService


AUTH_URL = "https://auth.example/authorize?client_id=abc"


def _server(auth_type=MCPAuthType.oauth2) -> MCPServerDB:
    return MCPServerDB(
        id=uuid4(), name="Example", url="https://mcp.example.com", auth_type=auth_type
    )


# ---------------------------------------------------------------------------
# as_oauth_required — the unwrap
# ---------------------------------------------------------------------------


def test_finds_the_requirement_however_deeply_it_is_wrapped():
    needed = OAuthAuthorizationRequired(AUTH_URL)
    nested = ExceptionGroup(
        "outer", [ExceptionGroup("inner", [ValueError("noise"), needed])]
    )

    assert as_oauth_required(needed) is needed
    assert as_oauth_required(nested) is needed


def test_leaves_unrelated_failures_alone():
    assert as_oauth_required(ValueError("noise")) is None
    assert as_oauth_required(ExceptionGroup("g", [ValueError("noise")])) is None


# ---------------------------------------------------------------------------
# the seam
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _transport_raising(exc):
    """A `streamablehttp_client` whose handshake fails with `exc`."""
    raise exc
    yield  # pragma: no cover — unreachable, keeps this an async generator


async def test_the_seam_unwraps_the_transports_exception_group(monkeypatch):
    """The whole reason the global handler existed: the implicit 401 arrives
    wrapped, so a plain `except OAuthAuthorizationRequired` used to miss it."""
    needed = OAuthAuthorizationRequired(AUTH_URL)
    monkeypatch.setattr(
        connectivity,
        "streamablehttp_client",
        lambda **kwargs: _transport_raising(ExceptionGroup("tg", [needed])),
    )

    with pytest.raises(OAuthAuthorizationRequired) as exc_info:
        async with connectivity._open_session("https://mcp.example.com"):
            pass

    assert exc_info.value.url == AUTH_URL


async def test_the_seam_leaves_other_failures_wrapped_as_they_were(monkeypatch):
    monkeypatch.setattr(
        connectivity,
        "streamablehttp_client",
        lambda **kwargs: _transport_raising(ExceptionGroup("tg", [ValueError("boom")])),
    )

    with pytest.raises(ExceptionGroup):
        async with connectivity._open_session("https://mcp.example.com"):
            pass


async def test_a_tools_list_that_401s_is_not_laundered_into_a_domain_error(monkeypatch):
    """`ExceptionGroup` is an `Exception`, so the `except Exception` that turns
    tool-listing failures into a clean `DomainError` would swallow a wrapped
    requirement before the seam's unwrap could see it."""

    @asynccontextmanager
    async def _transport(**_kwargs):
        yield (MagicMock(), MagicMock(), None)

    session = AsyncMock()
    session.initialize = AsyncMock()
    session.list_tools = AsyncMock(
        side_effect=ExceptionGroup("tg", [OAuthAuthorizationRequired(AUTH_URL)])
    )
    monkeypatch.setattr(connectivity, "streamablehttp_client", _transport)
    monkeypatch.setattr(
        connectivity, "ClientSession", lambda *a, **k: _async_cm(session)
    )

    with pytest.raises(OAuthAuthorizationRequired) as exc_info:
        async with connectivity._open_session("https://mcp.example.com"):
            pass

    assert exc_info.value.url == AUTH_URL


async def test_a_tools_list_failure_is_still_a_domain_error(monkeypatch):
    @asynccontextmanager
    async def _transport(**_kwargs):
        yield (MagicMock(), MagicMock(), None)

    session = AsyncMock()
    session.initialize = AsyncMock()
    session.list_tools = AsyncMock(side_effect=RuntimeError("server hung up"))
    monkeypatch.setattr(connectivity, "streamablehttp_client", _transport)
    monkeypatch.setattr(
        connectivity, "ClientSession", lambda *a, **k: _async_cm(session)
    )

    with pytest.raises(DomainError, match="server hung up"):
        async with connectivity._open_session("https://mcp.example.com"):
            pass


async def test_the_seam_does_not_touch_an_error_from_the_callers_body(monkeypatch):
    """P1-14's boundary, re-checked now that a `try` wraps the yield again."""

    @asynccontextmanager
    async def _transport(**_kwargs):
        yield (MagicMock(), MagicMock(), None)

    session = AsyncMock()
    session.initialize = AsyncMock()
    session.list_tools = AsyncMock(return_value=MagicMock(tools=[], nextCursor=None))
    monkeypatch.setattr(connectivity, "streamablehttp_client", _transport)
    monkeypatch.setattr(
        connectivity, "ClientSession", lambda *a, **k: _async_cm(session)
    )

    with pytest.raises(NotFoundError):
        async with connectivity._open_session("https://mcp.example.com"):
            raise NotFoundError("the caller's own problem")


def _async_cm(value):
    @asynccontextmanager
    async def _cm():
        yield value

    return _cm()


# ---------------------------------------------------------------------------
# list-tools: an answer, not an exception
# ---------------------------------------------------------------------------


async def _list_tools(*, authorized: bool, connect=None, initiate=None):
    service = MCPServerService(AsyncMock())
    with (
        patch(
            "app.mcp.servers.service.is_authorized",
            new=AsyncMock(return_value=authorized),
        ),
        patch(
            "app.mcp.servers.service.initiate_oauth",
            new=initiate or AsyncMock(side_effect=OAuthAuthorizationRequired(AUTH_URL)),
        ),
        patch(
            "app.mcp.servers.service.connect_to_server",
            connect or (lambda *a, **k: _async_cm((MagicMock(), []))),
        ),
    ):
        return await service.list_tools(_server(), "user-1")


async def test_list_tools_returns_the_auth_url_for_an_unconnected_server():
    result = await _list_tools(authorized=False)

    assert isinstance(result, AuthorizationRequired)
    assert result.status == "auth_required"
    assert result.auth_url == AUTH_URL


async def test_list_tools_returns_the_auth_url_when_the_handshake_401s(monkeypatch):
    """A token the server revoked looks authorized until the handshake, so the
    *implicit* 401 must reach the same answer as the explicit one.

    This one runs the real `connect_to_server` and the real `_open_session`, and
    fails the transport with the wrapped form the anyio task group actually
    produces — a mocked `connect_to_server` would skip the seam that unwraps it
    and prove nothing about this path. `auth_type=none` keeps the credential
    resolution out of it.
    """
    needed = OAuthAuthorizationRequired(AUTH_URL)
    monkeypatch.setattr(
        connectivity,
        "streamablehttp_client",
        lambda **kwargs: _transport_raising(ExceptionGroup("tg", [needed])),
    )
    service = MCPServerService(AsyncMock())

    result = await service.list_tools(_server(MCPAuthType.none), "user-1")

    assert isinstance(result, AuthorizationRequired)
    assert result.auth_url == AUTH_URL


async def test_list_tools_returns_tools_when_connected():
    tool = MagicMock()
    tool.name = "search"
    tool.description = "Search things"

    def _connect(*_args, **_kwargs):
        return _async_cm((MagicMock(), [tool]))

    result = await _list_tools(authorized=True, connect=_connect)

    assert isinstance(result, ToolsListed)
    assert result.status == "ok"
    assert [t.name for t in result.tools] == ["search"]


async def test_list_tools_still_fails_loudly_on_a_real_error():
    """Only the authorization condition is an answer; a broken server is not."""

    def _connect(*_args, **_kwargs):
        @asynccontextmanager
        async def _cm():
            raise DomainError("connection refused")
            yield  # pragma: no cover

        return _cm()

    with pytest.raises(DomainError):
        await _list_tools(authorized=True, connect=_connect)


# ---------------------------------------------------------------------------
# and nowhere else
# ---------------------------------------------------------------------------


def test_the_app_registers_no_oauth_or_exception_group_handler():
    """A guard, not a tautology: re-adding either handler would quietly restore
    "any endpoint touching MCP can answer 401 with an auth URL", and the
    ExceptionGroup one would again swallow TaskGroup-wrapped domain exceptions
    into 500s (§2.3). If a new global handler is genuinely wanted, this test is
    the place to argue for it."""
    from app.main import app

    registered = set(app.exception_handlers)

    assert OAuthAuthorizationRequired not in registered
    assert ExceptionGroup not in registered
    assert BaseExceptionGroup not in registered
