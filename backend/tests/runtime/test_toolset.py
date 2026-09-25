"""Unit tests for Toolset — name sanitization, tool filtering, UI metadata, bound_artifacts()."""

from uuid import uuid4

import pytest
from langchain_core.tools import Tool

from app.runtime.toolset import (
    AgentTool,
    Toolset,
    _build_tool_ui_metadata,
    _extract_mcp_app_resource_uri,
    _sanitize_tools_in_place,
    sanitize_tool_name,
)
from app.utils.encryption import encrypt_value


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


def _mcp_meta(meta: dict | None) -> dict:
    """The tool metadata `langchain.mcp` attaches: the server's `_meta` under
    `metadata["mcp"]["tool"]`."""
    return {"mcp": {"tool": {"_meta": meta}}}


class TestExtractMcpAppResourceUri:
    def test_standard_ui_key(self):
        tool = _make_tool(
            "t", metadata=_mcp_meta({"ui": {"resourceUri": "https://example.com"}})
        )
        assert _extract_mcp_app_resource_uri(tool) == "https://example.com"

    def test_namespaced_ui_key(self):
        tool = _make_tool(
            "t",
            metadata=_mcp_meta(
                {"io.modelcontextprotocol/ui": {"resourceUri": "https://x.com"}}
            ),
        )
        assert _extract_mcp_app_resource_uri(tool) == "https://x.com"

    def test_no_metadata(self):
        tool = _make_tool("t")
        assert _extract_mcp_app_resource_uri(tool) is None

    def test_metadata_without_mcp_provenance(self):
        tool = _make_tool("t", metadata={"_meta": {"ui": {"resourceUri": "x"}}})
        assert _extract_mcp_app_resource_uri(tool) is None

    def test_no_resource_uri(self):
        tool = _make_tool("t", metadata=_mcp_meta({"ui": {"other": "val"}}))
        assert _extract_mcp_app_resource_uri(tool) is None

    def test_whitespace_stripped(self):
        tool = _make_tool(
            "t", metadata=_mcp_meta({"ui": {"resourceUri": "  https://x.com  "}})
        )
        assert _extract_mcp_app_resource_uri(tool) == "https://x.com"

    def test_empty_string_returns_none(self):
        tool = _make_tool("t", metadata=_mcp_meta({"ui": {"resourceUri": "  "}}))
        assert _extract_mcp_app_resource_uri(tool) is None


# ---------------------------------------------------------------------------
# _build_tool_ui_metadata
# ---------------------------------------------------------------------------


class TestBuildToolUiMetadata:
    def test_returns_metadata_for_app_tool(self):
        tool = _make_tool(
            "sheets_read",
            metadata=_mcp_meta({"ui": {"resourceUri": "https://example.com"}}),
        )
        assert _build_tool_ui_metadata(tool, "server-1") == {
            "mcp_app_resource_uri": "https://example.com",
            "mcp_server_id": "server-1",
        }

    def test_no_resource_uri_returns_none(self):
        tool = _make_tool("sheets_read")  # no metadata
        assert _build_tool_ui_metadata(tool, "s1") is None


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
# bound_artifacts
# ---------------------------------------------------------------------------


class TestBoundArtifacts:
    """Every tool is wrapped — app tools to stamp their UI metadata, the rest to
    drop structured content (the runtime behaviour is covered in
    tests/mcp/client/test_tools.py)."""

    def test_wraps_app_tools(self):
        tool = _make_tool("my_tool")
        original_coro = tool.coroutine
        at = AgentTool(
            tool=tool,
            ui_metadata={
                "mcp_app_resource_uri": "https://x.com",
                "mcp_server_id": "s1",
            },
        )
        Toolset(tools=[at]).bound_artifacts(ui=True)
        assert tool.coroutine is not original_coro

    def test_wraps_plain_tools_too(self):
        tool = _make_tool("my_tool")
        original_coro = tool.coroutine
        Toolset(tools=[AgentTool(tool=tool, ui_metadata=None)]).bound_artifacts(ui=True)
        assert tool.coroutine is not original_coro

    @staticmethod
    def _tool_returning(result) -> Tool:
        async def coroutine(**kwargs):
            return result

        return Tool(name="t", description="", func=lambda: None, coroutine=coroutine)

    @pytest.mark.asyncio
    async def test_ui_true_stamps_app_tools_and_strips_plain_ones(self):
        app_tool = self._tool_returning(("ok", {"structured_content": {"rows": [1]}}))
        plain = self._tool_returning(("ok", {"structured_content": {"big": "x" * 10}}))
        ui = {"mcp_app_resource_uri": "ui://app", "mcp_server_id": "s1"}
        Toolset(
            tools=[
                AgentTool(tool=app_tool, ui_metadata=ui),
                AgentTool(tool=plain, ui_metadata=None),
            ]
        ).bound_artifacts(ui=True)
        _, app_artifact = await app_tool.coroutine()
        _, plain_artifact = await plain.coroutine()
        assert app_artifact == {"structured_content": {"rows": [1]}, **ui}
        assert plain_artifact is None

    @pytest.mark.asyncio
    async def test_ui_false_strips_even_app_tools(self):
        """Subagent toolsets never stream widgets, so their app tools are
        bounded like any other tool."""
        app_tool = self._tool_returning(("ok", {"structured_content": {"rows": [1]}}))
        ui = {"mcp_app_resource_uri": "ui://app", "mcp_server_id": "s1"}
        Toolset(tools=[AgentTool(tool=app_tool, ui_metadata=ui)]).bound_artifacts(
            ui=False
        )
        _, artifact = await app_tool.coroutine()
        assert artifact is None

    def test_idempotent(self):
        """Wrapping twice wraps twice, and does not crash."""
        tool = _make_tool("my_tool")
        at = AgentTool(
            tool=tool,
            ui_metadata={
                "mcp_app_resource_uri": "https://x.com",
                "mcp_server_id": "s1",
            },
        )
        ts = Toolset(tools=[at])
        ts.bound_artifacts(ui=True)
        coro_after_first = tool.coroutine
        ts.bound_artifacts(ui=True)
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
        assert prepared.connections == {}

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


class _CountingDB:
    """A DB that answers both queries `prepare` makes, and counts them."""

    def __init__(self, servers, api_key_rows):
        self._servers = servers
        self._api_key_rows = api_key_rows
        self.server_queries = 0
        self.api_key_queries = 0

    async def execute(self, stmt):
        table = stmt.get_final_froms()[0].name
        if table == "mcp_servers":
            self.server_queries += 1
            return _FakeResult(self._servers)
        self.api_key_queries += 1
        return _ScalarOneResult(self._api_key_rows)


class _ScalarOneResult:
    def __init__(self, rows):
        self._rows = rows

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class TestMCPResolutionScope:
    """A run graph is a parent plus subagents, usually over the same servers.
    Resolving each agent independently cost one server read and one API-key
    decrypt per agent; the shared scope makes both O(1) for the graph."""

    @staticmethod
    def _fixture():
        from types import SimpleNamespace

        from app.mcp.servers.models import MCPAuthType, MCPServerDB

        server_id = uuid4()
        server = MCPServerDB(
            id=server_id,
            name="sheets",
            url="http://mcp.example.com",
            auth_type=MCPAuthType.api_key,
        )
        binding = SimpleNamespace(mcp_server_id=server_id, tools=None)
        key_row = SimpleNamespace(key_encrypted=encrypt_value("s3cret"))
        return server, binding, key_row

    @pytest.mark.asyncio
    async def test_a_shared_scope_reads_each_server_once(self):
        from app.runtime.toolset import MCPResolutionScope

        server, binding, key_row = self._fixture()
        db = _CountingDB([server], [key_row])

        scope = await MCPResolutionScope.build([binding, binding], db, "u1")
        for _ in range(3):  # a parent and two subagents on the same server
            prepared = await Toolset.prepare(
                [binding], db=db, user_id="u1", apply_ui=False, scope=scope
            )
            assert prepared.server_names == ["sheets"]

        assert db.server_queries == 1
        assert db.api_key_queries == 1

    @pytest.mark.asyncio
    async def test_without_a_scope_each_agent_reads_for_itself(self):
        """The default stays per-agent, so the API paths that prepare a single
        agent don't have to build a scope to call `prepare`."""
        from app.runtime.toolset import MCPResolutionScope  # noqa: F401

        server, binding, key_row = self._fixture()
        db = _CountingDB([server], [key_row])

        for _ in range(3):
            await Toolset.prepare([binding], db=db, user_id="u1", apply_ui=False)

        assert db.server_queries == 3
        assert db.api_key_queries == 3

    @pytest.mark.asyncio
    async def test_the_shared_key_still_reaches_the_connection_spec(self):
        """Sharing the decrypted key must not change what the client is given."""
        from app.runtime.toolset import MCPResolutionScope

        server, binding, key_row = self._fixture()
        db = _CountingDB([server], [key_row])

        scope = await MCPResolutionScope.build([binding], db, "u1")
        spec = await scope.connection(server)

        assert spec.headers == {"Authorization": "Bearer s3cret"}
