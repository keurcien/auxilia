"""Unit tests for Toolset — name sanitization, tool filtering, UI metadata, apply_ui_metadata()."""

from uuid import uuid4

import pytest
from langchain_core.tools import Tool

from app.agents.toolset import (
    AgentTool,
    Toolset,
    _build_tool_ui_metadata,
    _extract_mcp_app_resource_uri,
    _resolve_server_name_from_prefixed_tool_name,
    _sanitize_tools_in_place,
    sanitize_tool_name,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool(name: str, metadata: dict | None = None) -> Tool:
    """Create a minimal Tool with an async coroutine for testing."""

    async def _noop(**kwargs):
        return "ok"

    return Tool(
        name=name,
        description="test",
        coroutine=_noop,
        func=lambda: None,
        metadata=metadata,
    )


def _make_agent_tool(
    name: str,
    requires_approval: bool = False,
    ui_metadata: dict | None = None,
    metadata: dict | None = None,
) -> AgentTool:
    return AgentTool(
        tool=_make_tool(name, metadata=metadata),
        requires_approval=requires_approval,
        ui_metadata=ui_metadata,
    )


class _FakeMCPServer:
    """Minimal stand-in for MCPServerDB in metadata tests."""

    def __init__(self, name: str, id: str | None = None):
        self.name = name
        self.id = id or str(uuid4())


# ---------------------------------------------------------------------------
# sanitize_tool_name
# ---------------------------------------------------------------------------


class TestSanitizeToolName:
    def test_invalid_chars_replaced(self):
        assert (
            sanitize_tool_name("google-sheets.read_range") == "google-sheets_read_range"
        )

    def test_preserves_valid_chars(self):
        assert sanitize_tool_name("my_tool-123") == "my_tool-123"

    def test_length_truncation(self):
        long_name = "a" * 200
        result = sanitize_tool_name(long_name)
        assert len(result) <= 128

    def test_empty_name_fallback(self):
        assert sanitize_tool_name("") == "tool"

    def test_whitespace_only_fallback(self):
        assert sanitize_tool_name("...") == "tool"

    def test_strips_leading_trailing_underscores(self):
        assert sanitize_tool_name(".hello.") == "hello"


# ---------------------------------------------------------------------------
# _sanitize_tools_in_place
# ---------------------------------------------------------------------------


class TestSanitizeToolsInPlace:
    def test_basic_sanitization(self):
        t = _make_tool("google-sheets.read")
        name_map = _sanitize_tools_in_place([t])
        assert t.name == "google-sheets_read"
        assert name_map["google-sheets.read"] == "google-sheets_read"

    def test_collision_dedup(self):
        t1 = _make_tool("foo.bar")
        t2 = _make_tool("foo!bar")  # both sanitize to foo_bar
        _sanitize_tools_in_place([t1, t2])
        assert t1.name == "foo_bar"
        assert t2.name == "foo_bar_2"

    def test_triple_collision(self):
        tools = [_make_tool("a.b"), _make_tool("a!b"), _make_tool("a@b")]
        _sanitize_tools_in_place(tools)
        names = [t.name for t in tools]
        assert names == ["a_b", "a_b_2", "a_b_3"]

    def test_no_mutation_when_already_valid(self):
        t = _make_tool("valid_name")
        name_map = _sanitize_tools_in_place([t])
        assert t.name == "valid_name"
        assert name_map["valid_name"] == "valid_name"


# ---------------------------------------------------------------------------
# _extract_mcp_app_resource_uri
# ---------------------------------------------------------------------------


class TestExtractMcpAppResourceUri:
    def test_standard_ui_key(self):
        tool = _make_tool(
            "t", metadata={"_meta": {"ui": {"resourceUri": "https://example.com"}}}
        )
        assert _extract_mcp_app_resource_uri(tool) == "https://example.com"

    def test_namespaced_ui_key(self):
        tool = _make_tool(
            "t",
            metadata={
                "_meta": {
                    "io.modelcontextprotocol/ui": {"resourceUri": "https://x.com"}
                }
            },
        )
        assert _extract_mcp_app_resource_uri(tool) == "https://x.com"

    def test_no_metadata(self):
        tool = _make_tool("t")
        assert _extract_mcp_app_resource_uri(tool) is None

    def test_no_resource_uri(self):
        tool = _make_tool("t", metadata={"_meta": {"ui": {"other": "val"}}})
        assert _extract_mcp_app_resource_uri(tool) is None

    def test_whitespace_stripped(self):
        tool = _make_tool(
            "t",
            metadata={"_meta": {"ui": {"resourceUri": "  https://x.com  "}}},
        )
        assert _extract_mcp_app_resource_uri(tool) == "https://x.com"

    def test_empty_string_returns_none(self):
        tool = _make_tool("t", metadata={"_meta": {"ui": {"resourceUri": "  "}}})
        assert _extract_mcp_app_resource_uri(tool) is None


# ---------------------------------------------------------------------------
# _resolve_server_name_from_prefixed_tool_name
# ---------------------------------------------------------------------------


class TestResolveServerName:
    def test_exact_match(self):
        assert (
            _resolve_server_name_from_prefixed_tool_name("sheets", ["sheets"])
            == "sheets"
        )

    def test_prefix_match(self):
        assert (
            _resolve_server_name_from_prefixed_tool_name("sheets_read", ["sheets"])
            == "sheets"
        )

    def test_longest_prefix_wins(self):
        result = _resolve_server_name_from_prefixed_tool_name(
            "google-sheets_read", ["google", "google-sheets"]
        )
        assert result == "google-sheets"

    def test_no_match(self):
        assert (
            _resolve_server_name_from_prefixed_tool_name("unknown_tool", ["sheets"])
            is None
        )


# ---------------------------------------------------------------------------
# _build_tool_ui_metadata
# ---------------------------------------------------------------------------


class TestBuildToolUiMetadata:
    def test_returns_metadata_for_matching_tool(self):
        tool = _make_tool(
            "sheets_read",
            metadata={"_meta": {"ui": {"resourceUri": "https://example.com"}}},
        )
        result = _build_tool_ui_metadata(
            tool,
            server_id_by_name={"sheets": "server-1"},
            server_names=["sheets"],
        )
        assert result == {
            "mcp_app_resource_uri": "https://example.com",
            "mcp_server_id": "server-1",
        }

    def test_no_resource_uri_returns_none(self):
        tool = _make_tool("sheets_read")  # no metadata
        result = _build_tool_ui_metadata(
            tool,
            server_id_by_name={"sheets": "s1"},
            server_names=["sheets"],
        )
        assert result is None

    def test_no_matching_server_returns_none(self):
        tool = _make_tool(
            "sheets_read",
            metadata={"_meta": {"ui": {"resourceUri": "https://example.com"}}},
        )
        result = _build_tool_ui_metadata(
            tool,
            server_id_by_name={"other": "s1"},
            server_names=["other"],
        )
        assert result is None


# ---------------------------------------------------------------------------
# Toolset properties
# ---------------------------------------------------------------------------


class TestToolsetProperties:
    def test_all_returns_lc_tools(self):
        at1 = _make_agent_tool("a")
        at2 = _make_agent_tool("b", requires_approval=True)
        ts = Toolset(tools=[at1, at2])
        assert ts.all == [at1.tool, at2.tool]

    def test_interrupt_on(self):
        at1 = _make_agent_tool("tool_a", requires_approval=True)
        at2 = _make_agent_tool("tool_b", requires_approval=True)
        at3 = _make_agent_tool("tool_c", requires_approval=False)
        ts = Toolset(tools=[at1, at2, at3])
        assert ts.interrupt_on == {"tool_a": True, "tool_b": True}

    def test_empty_toolset(self):
        ts = Toolset(tools=[])
        assert ts.all == []
        assert ts.interrupt_on == {}


# ---------------------------------------------------------------------------
# apply_ui_metadata
# ---------------------------------------------------------------------------


class TestApplyUiMetadata:
    def test_injects_metadata(self):
        tool = _make_tool("my_tool")
        original_coro = tool.coroutine
        at = AgentTool(
            tool=tool,
            ui_metadata={
                "mcp_app_resource_uri": "https://x.com",
                "mcp_server_id": "s1",
            },
        )
        ts = Toolset(tools=[at])
        ts.apply_ui_metadata()
        assert tool.coroutine is not original_coro

    def test_no_metadata_leaves_unwrapped(self):
        tool = _make_tool("my_tool")
        original_coro = tool.coroutine
        at = AgentTool(tool=tool, ui_metadata=None)
        ts = Toolset(tools=[at])
        ts.apply_ui_metadata()
        assert tool.coroutine is original_coro

    def test_idempotent(self):
        """Calling apply_ui_metadata twice should wrap twice but not crash."""
        tool = _make_tool("my_tool")
        at = AgentTool(
            tool=tool,
            ui_metadata={
                "mcp_app_resource_uri": "https://x.com",
                "mcp_server_id": "s1",
            },
        )
        ts = Toolset(tools=[at])
        ts.apply_ui_metadata()
        coro_after_first = tool.coroutine
        ts.apply_ui_metadata()
        assert tool.coroutine is not coro_after_first


# ---------------------------------------------------------------------------
# Toolset.prepare / open — empty bindings
# ---------------------------------------------------------------------------


class TestToolsetPrepareEmpty:
    @pytest.mark.asyncio
    async def test_empty_bindings_prepare(self):
        prepared = await Toolset.prepare([], db=None, user_id="u1", apply_ui=True)
        assert prepared.server_names == []
        assert prepared.interrupt_on == {}
        assert prepared.client is None

    @pytest.mark.asyncio
    async def test_empty_bindings_open_yields_empty_toolset(self):
        prepared = await Toolset.prepare([], db=None, user_id="u1", apply_ui=True)
        async with Toolset.open(prepared) as ts:
            assert ts.tools == []
            assert ts.all == []


# ---------------------------------------------------------------------------
# Toolset.prepare — interrupt_on derived from the persisted tool map
# ---------------------------------------------------------------------------


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class _FakeDB:
    def __init__(self, rows):
        self._rows = rows

    async def execute(self, stmt):
        return _FakeResult(self._rows)


class TestPrepareDerivesInterruptOn:
    @pytest.mark.asyncio
    async def test_needs_approval_tools_gate_without_network(self):
        from types import SimpleNamespace

        from app.mcp.servers.models import MCPAuthType, MCPServerDB

        server_id = uuid4()
        server = MCPServerDB(
            id=server_id,
            name="sheets",
            url="http://mcp.example.com",
            auth_type=MCPAuthType.none,
        )
        binding = SimpleNamespace(
            mcp_server_id=server_id,
            tools={
                "read.range": "needs_approval",
                "write_range": "always_allow",
                "delete_sheet": "disabled",
            },
        )
        prepared = await Toolset.prepare(
            [binding], db=_FakeDB([server]), user_id="u1", apply_ui=True
        )
        # Prefixed name sanitized the same way live tool names are at open time.
        assert prepared.interrupt_on == {"sheets_read_range": True}
        assert prepared.server_names == ["sheets"]

    @pytest.mark.asyncio
    async def test_null_tool_map_yields_no_gates(self):
        from types import SimpleNamespace

        from app.mcp.servers.models import MCPAuthType, MCPServerDB

        server_id = uuid4()
        server = MCPServerDB(
            id=server_id,
            name="sheets",
            url="http://mcp.example.com",
            auth_type=MCPAuthType.none,
        )
        binding = SimpleNamespace(mcp_server_id=server_id, tools=None)
        prepared = await Toolset.prepare(
            [binding], db=_FakeDB([server]), user_id="u1", apply_ui=True
        )
        assert prepared.interrupt_on == {}


# ---------------------------------------------------------------------------
# _open_sessions — concurrent, task-owned session lifecycles
# ---------------------------------------------------------------------------


class _FakeSessionCM:
    """Records which task enters/exits, to assert anyio-safe ownership."""

    def __init__(self, name, log, delay=0.0, fail_enter=False, fail_exit=False):
        self.name = name
        self.log = log
        self.delay = delay
        self.fail_enter = fail_enter
        self.fail_exit = fail_exit

    async def __aenter__(self):
        import asyncio

        self.log.append(("enter", self.name, asyncio.current_task()))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail_enter:
            raise RuntimeError(f"enter failed: {self.name}")
        return f"session-{self.name}"

    async def __aexit__(self, *exc):
        import asyncio

        self.log.append(("exit", self.name, asyncio.current_task()))
        if self.fail_exit:
            raise RuntimeError(f"exit failed: {self.name}")
        return False


class _FakeClient:
    def __init__(self, cms):
        self._cms = cms

    def session(self, name):
        return self._cms[name]


class TestOpenSessions:
    @pytest.mark.asyncio
    async def test_sessions_open_concurrently(self):
        import time as time_mod

        from app.agents.toolset import _open_sessions

        log = []
        cms = {
            "a": _FakeSessionCM("a", log, delay=0.05),
            "b": _FakeSessionCM("b", log, delay=0.05),
        }
        t0 = time_mod.perf_counter()
        async with _open_sessions(_FakeClient(cms), ["a", "b"]) as sessions:
            assert sessions == {"a": "session-a", "b": "session-b"}
        elapsed = time_mod.perf_counter() - t0
        assert elapsed < 0.09  # serial would be >= 0.10

    @pytest.mark.asyncio
    async def test_enter_and_exit_happen_in_same_task(self):
        import asyncio

        from app.agents.toolset import _open_sessions

        log = []
        cms = {"a": _FakeSessionCM("a", log), "b": _FakeSessionCM("b", log)}
        async with _open_sessions(_FakeClient(cms), ["a", "b"]):
            pass
        main_task = asyncio.current_task()
        by_name: dict[str, dict] = {}
        for event, name, task in log:
            by_name.setdefault(name, {})[event] = task
        for name, events in by_name.items():
            assert events["enter"] is events["exit"], name
            assert events["enter"] is not main_task, name

    @pytest.mark.asyncio
    async def test_enter_failure_propagates_and_cleans_up_others(self):
        from app.agents.toolset import _open_sessions

        log = []
        cms = {
            "ok": _FakeSessionCM("ok", log, delay=0.01),
            "bad": _FakeSessionCM("bad", log, fail_enter=True),
        }
        with pytest.raises(RuntimeError, match="enter failed: bad"):
            async with _open_sessions(_FakeClient(cms), ["ok", "bad"]):
                pytest.fail("body must not run when a session fails to open")
        assert any(e == "exit" and n == "ok" for e, n, _ in log)

    @pytest.mark.asyncio
    async def test_teardown_failure_propagates(self):
        from app.agents.toolset import _open_sessions

        log = []
        cms = {"a": _FakeSessionCM("a", log, fail_exit=True)}
        with pytest.raises(RuntimeError, match="exit failed: a"):
            async with _open_sessions(_FakeClient(cms), ["a"]):
                pass

    @pytest.mark.asyncio
    async def test_body_exception_wins_over_teardown_error(self):
        from app.agents.toolset import _open_sessions

        log = []
        cms = {"a": _FakeSessionCM("a", log, fail_exit=True)}
        with pytest.raises(ValueError, match="body boom"):
            async with _open_sessions(_FakeClient(cms), ["a"]):
                raise ValueError("body boom")
        assert any(e == "exit" and n == "a" for e, n, t in log)

    @pytest.mark.asyncio
    async def test_replaced_session_teardown_error_is_excused(self):
        """A dead primary that was replaced mid-stream tears down noisily —
        that error must be logged, not raised at the end of a successful run."""
        from app.agents.toolset import _open_sessions

        log = []
        cms = {
            "dead": _FakeSessionCM("dead", log, fail_exit=True),
            "ok": _FakeSessionCM("ok", log),
        }
        async with _open_sessions(
            _FakeClient(cms), ["dead", "ok"], replaced={"dead"}
        ) as sessions:
            assert sessions["dead"] == "session-dead"

    @pytest.mark.asyncio
    async def test_unreplaced_teardown_error_still_raises(self):
        from app.agents.toolset import _open_sessions

        log = []
        cms = {"a": _FakeSessionCM("a", log, fail_exit=True)}
        with pytest.raises(RuntimeError, match="exit failed: a"):
            async with _open_sessions(_FakeClient(cms), ["a"], replaced={"other"}):
                pass


# ---------------------------------------------------------------------------
# ReconnectingSession — retry-once on dead transport
# ---------------------------------------------------------------------------


class _FakeSession:
    """Stand-in ClientSession: fails every request with `fail_with` if set."""

    def __init__(self, name: str, fail_with: BaseException | None = None):
        self.name = name
        self.calls: list[str] = []
        self.fail_with = fail_with

    async def call_tool(self, tool_name, args=None, **kwargs):
        self.calls.append(tool_name)
        if self.fail_with is not None:
            raise self.fail_with
        return f"{self.name}:{tool_name}"

    async def list_tools(self, cursor=None):
        if self.fail_with is not None:
            raise self.fail_with
        return f"tools-from-{self.name}"


class _FakeSupervisor:
    """Hands out pre-baked replacement sessions and counts reopens."""

    def __init__(self, replacements: list[_FakeSession]):
        self._replacements = list(replacements)
        self.reopened: list[str] = []
        self.replaced: set[str] = set()

    async def reopen(self, name: str):
        self.reopened.append(name)
        self.replaced.add(name)
        return self._replacements.pop(0)


class TestReconnectingSession:
    @pytest.mark.asyncio
    async def test_dead_transport_reconnects_and_retries(self):
        import anyio

        from app.agents.toolset import ReconnectingSession

        dead = _FakeSession("dead", fail_with=anyio.ClosedResourceError())
        fresh = _FakeSession("fresh")
        supervisor = _FakeSupervisor([fresh])
        proxy = ReconnectingSession("slack", dead, supervisor)

        result = await proxy.call_tool("read_channel")

        assert result == "fresh:read_channel"
        assert supervisor.reopened == ["slack"]
        # The failed call never reached the server; the retry did.
        assert dead.calls == ["read_channel"]
        assert fresh.calls == ["read_channel"]

    @pytest.mark.asyncio
    async def test_non_transport_errors_are_not_retried(self):
        from app.agents.toolset import ReconnectingSession

        dead = _FakeSession("dead", fail_with=ValueError("mid-flight failure"))
        supervisor = _FakeSupervisor([])
        proxy = ReconnectingSession("slack", dead, supervisor)

        with pytest.raises(ValueError, match="mid-flight failure"):
            await proxy.call_tool("send_message")
        assert supervisor.reopened == []

    @pytest.mark.asyncio
    async def test_concurrent_failures_reconnect_once(self):
        """N concurrent calls on a dead session must trigger ONE reopen, and
        all of them must retry on the same replacement."""
        import asyncio

        import anyio

        from app.agents.toolset import ReconnectingSession

        dead = _FakeSession("dead", fail_with=anyio.ClosedResourceError())
        fresh = _FakeSession("fresh")
        supervisor = _FakeSupervisor([fresh])
        proxy = ReconnectingSession("slack", dead, supervisor)

        results = await asyncio.gather(
            proxy.call_tool("a"), proxy.call_tool("b"), proxy.call_tool("c")
        )

        assert sorted(results) == ["fresh:a", "fresh:b", "fresh:c"]
        assert supervisor.reopened == ["slack"]

    @pytest.mark.asyncio
    async def test_second_death_reconnects_again(self):
        import anyio

        from app.agents.toolset import ReconnectingSession

        dead1 = _FakeSession("dead1", fail_with=anyio.BrokenResourceError())
        dead2 = _FakeSession("dead2", fail_with=anyio.BrokenResourceError())
        fresh = _FakeSession("fresh")
        supervisor = _FakeSupervisor([dead2, fresh])
        proxy = ReconnectingSession("slack", dead1, supervisor)

        # First call: dead1 -> reopen -> dead2 -> retry fails (one retry only).
        with pytest.raises(anyio.BrokenResourceError):
            await proxy.call_tool("a")
        # Next call fails on dead2, reopens again onto fresh, succeeds.
        assert await proxy.call_tool("b") == "fresh:b"
        assert supervisor.reopened == ["slack", "slack"]

    @pytest.mark.asyncio
    async def test_list_tools_reconnects_and_retries(self):
        """Tool discovery (Toolset.open → load_mcp_tools → list_tools) must
        survive a transport that died right after the session opened, not
        abort the whole run at setup."""
        import anyio

        from app.agents.toolset import ReconnectingSession

        dead = _FakeSession("dead", fail_with=anyio.ClosedResourceError())
        fresh = _FakeSession("fresh")
        supervisor = _FakeSupervisor([fresh])
        proxy = ReconnectingSession("slack", dead, supervisor)

        assert await proxy.list_tools() == "tools-from-fresh"
        assert supervisor.reopened == ["slack"]

    @pytest.mark.asyncio
    async def test_getattr_delegates_to_current_session(self):
        import anyio

        from app.agents.toolset import ReconnectingSession

        dead = _FakeSession("dead", fail_with=anyio.ClosedResourceError())
        fresh = _FakeSession("fresh")
        supervisor = _FakeSupervisor([fresh])
        proxy = ReconnectingSession("slack", dead, supervisor)

        # `name` is not a wrapped method — it resolves on the live session.
        assert proxy.name == "dead"
        await proxy.call_tool("t")
        assert proxy.name == "fresh"


# ---------------------------------------------------------------------------
# _SessionSupervisor — replacement host lifecycle
# ---------------------------------------------------------------------------


class TestSessionSupervisor:
    @pytest.mark.asyncio
    async def test_reopen_hosts_session_and_records_replacement(self):
        import asyncio

        from app.agents.toolset import _SessionSupervisor

        log = []
        cms = {"a": _FakeSessionCM("a", log)}
        supervisor = _SessionSupervisor(_FakeClient(cms))

        session = await supervisor.reopen("a")
        assert session == "session-a"
        assert supervisor.replaced == {"a"}
        # Entered in a dedicated task, not the caller's.
        enter_task = next(t for e, n, t in log if e == "enter")
        assert enter_task is not asyncio.current_task()

        await supervisor.close()
        exit_task = next(t for e, n, t in log if e == "exit")
        assert exit_task is enter_task

    @pytest.mark.asyncio
    async def test_close_logs_teardown_errors_instead_of_raising(self):
        from app.agents.toolset import _SessionSupervisor

        log = []
        cms = {"a": _FakeSessionCM("a", log, fail_exit=True)}
        supervisor = _SessionSupervisor(_FakeClient(cms))
        await supervisor.reopen("a")

        await supervisor.close()  # must not raise

    @pytest.mark.asyncio
    async def test_reopen_failure_propagates_to_caller(self):
        from app.agents.toolset import _SessionSupervisor

        log = []
        cms = {"a": _FakeSessionCM("a", log, fail_enter=True)}
        supervisor = _SessionSupervisor(_FakeClient(cms))

        with pytest.raises(RuntimeError, match="enter failed: a"):
            await supervisor.reopen("a")
        assert supervisor.replaced == set()
        await supervisor.close()
