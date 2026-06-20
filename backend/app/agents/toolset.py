import asyncio
import logging
import re
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass

from langchain_core.tools import Tool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.agents.schemas import AgentMCPServerResponse
from app.mcp.client.factory import MCPClientConfigFactory
from app.mcp.client.tools import inject_ui_metadata_into_tool
from app.mcp.servers.models import MCPServerDB


logger = logging.getLogger(__name__)


_VALID_TOOL_NAME_CHARS = re.compile(r"[^a-zA-Z0-9_-]")
_MAX_TOOL_NAME_LENGTH = 128


def sanitize_tool_name(name: str) -> str:
    sanitized = _VALID_TOOL_NAME_CHARS.sub("_", name).strip("_")
    if not sanitized:
        sanitized = "tool"
    if len(sanitized) > _MAX_TOOL_NAME_LENGTH:
        sanitized = sanitized[:_MAX_TOOL_NAME_LENGTH].rstrip("_")
    return sanitized or "tool"


def _sanitize_tools_in_place(tools: list[Tool]) -> dict[str, str]:
    used_names: set[str] = set()
    name_map: dict[str, str] = {}

    for tool in tools:
        original_name = tool.name
        base_name = sanitize_tool_name(original_name)
        candidate = base_name
        suffix = 1

        while candidate in used_names:
            suffix += 1
            suffix_text = f"_{suffix}"
            max_base_length = _MAX_TOOL_NAME_LENGTH - len(suffix_text)
            truncated_base = base_name[:max_base_length].rstrip("_")
            if not truncated_base:
                truncated_base = "tool"
            candidate = f"{truncated_base}{suffix_text}"

        tool.name = candidate
        used_names.add(candidate)
        name_map[original_name] = candidate

    return name_map


def _extract_mcp_app_resource_uri(tool: Tool) -> str | None:
    metadata = getattr(tool, "metadata", None)
    if not isinstance(metadata, dict):
        return None

    raw_meta = metadata.get("_meta")
    if not isinstance(raw_meta, dict):
        return None

    ui_meta = raw_meta.get("ui")
    if not isinstance(ui_meta, dict):
        ui_meta = raw_meta.get("io.modelcontextprotocol/ui")
        if not isinstance(ui_meta, dict):
            return None

    resource_uri = ui_meta.get("resourceUri")
    if not isinstance(resource_uri, str):
        return None

    cleaned = resource_uri.strip()
    return cleaned if cleaned else None


def _resolve_server_name_from_prefixed_tool_name(
    prefixed_tool_name: str,
    server_names: list[str],
) -> str | None:
    for server_name in sorted(server_names, key=len, reverse=True):
        if prefixed_tool_name == server_name:
            return server_name
        if prefixed_tool_name.startswith(f"{server_name}_"):
            return server_name
    return None


def _build_tool_ui_metadata(
    tool: Tool,
    server_id_by_name: dict[str, str],
    server_names: list[str],
) -> dict[str, str] | None:
    resource_uri = _extract_mcp_app_resource_uri(tool)
    if not resource_uri:
        return None

    server_name = _resolve_server_name_from_prefixed_tool_name(
        tool.name, server_names
    )
    if not server_name:
        return None

    server_id = server_id_by_name.get(server_name)
    if not server_id:
        return None

    return {
        "mcp_app_resource_uri": resource_uri,
        "mcp_server_id": server_id,
    }


@dataclass
class AgentTool:
    """A resolved MCP tool with its approval status and UI metadata."""

    tool: Tool
    requires_approval: bool = False
    ui_metadata: dict[str, str] | None = None


@dataclass
class PreparedToolset:
    """DB-derived spec needed to (re)bind MCP tools onto a live session.

    Built at agent-build time (request scope, with the request DB), it carries
    everything required to open sessions and assemble tools later during the
    streaming response — without touching the DB. ``interrupt_on`` is computed
    here so HITL middleware can be wired at build time.
    """

    client: MultiServerMCPClient | None
    server_names: list[str]  # config keys (== MCP server names), in a fixed order
    tool_settings: dict[str, dict]
    server_id_by_name: dict[str, str]
    interrupt_on: dict[str, bool]  # sanitized tool name -> True
    apply_ui: bool


def _assemble_agent_tools(
    tools_by_server: list[tuple[str, list[Tool]]],
    tool_settings: dict[str, dict],
    server_id_by_name: dict[str, str],
) -> list[AgentTool]:
    """Filter -> build UI metadata -> sanitize, shared by prepare() and open().

    ``tools_by_server`` must be in the SAME server order (and each server's tools
    in the SAME order) across both call sites: ``_sanitize_tools_in_place`` is
    order-sensitive (dedup suffixes), so identical ordering is what guarantees the
    sanitized names computed at build (for ``interrupt_on``) match the names of the
    live tools opened at stream time.
    """
    server_names = list(server_id_by_name.keys())
    agent_tools: list[AgentTool] = []
    for server_id, lc_tools in tools_by_server:
        settings = tool_settings.get(str(server_id), {})
        allowed_names = {
            server_id + "_" + t
            for t, status in settings.items()
            if status == "always_allow"
        }
        approval_names = {
            server_id + "_" + t
            for t, status in settings.items()
            if status == "needs_approval"
        }
        for tool in lc_tools:
            if tool.name in allowed_names:
                agent_tools.append(AgentTool(tool=tool, requires_approval=False))
            elif tool.name in approval_names:
                agent_tools.append(AgentTool(tool=tool, requires_approval=True))
            # disabled or unknown tools are excluded

    # Build UI metadata before sanitization (uses original prefixed names).
    for at in agent_tools:
        at.ui_metadata = _build_tool_ui_metadata(
            at.tool, server_id_by_name, server_names
        )

    _sanitize_tools_in_place([at.tool for at in agent_tools])
    return agent_tools


class Toolset:
    """Resolved, ready-to-use tools from MCP servers."""

    def __init__(self, tools: list[AgentTool]):
        self.tools = tools

    @property
    def all(self) -> list[Tool]:
        return [t.tool for t in self.tools]

    @property
    def interrupt_on(self) -> dict[str, bool]:
        return {t.tool.name: True for t in self.tools if t.requires_approval}

    @classmethod
    async def prepare(
        cls,
        agent_mcp_servers: list[AgentMCPServerResponse],
        db: AsyncSession,
        user_id: str,
        *,
        apply_ui: bool,
    ) -> PreparedToolset:
        """Build-time phase: DB lookup -> configs -> discover tools -> interrupt_on.

        All DB access happens here (request scope). Tools are fetched once to learn
        their names/approval flags/UI metadata so ``interrupt_on`` is known at build
        time; the discovered tool objects are discarded — execution uses the
        persistent session opened by :meth:`open`.
        """
        empty = PreparedToolset(
            client=None,
            server_names=[],
            tool_settings={},
            server_id_by_name={},
            interrupt_on={},
            apply_ui=apply_ui,
        )
        if not agent_mcp_servers:
            return empty

        # 1. Load MCP server records from DB
        server_ids = [s.mcp_server_id for s in agent_mcp_servers]
        result = await db.execute(
            select(MCPServerDB).where(MCPServerDB.id.in_(server_ids))
        )
        mcp_servers = list(result.scalars().all())

        # 2. Build MCP client configs (resolves auth to Redis/header values — no
        #    live SQL handle is retained, so the client is safe to use later during
        #    streaming, after the request DB session has closed).
        mcp_factory = MCPClientConfigFactory(db=db, user_id=user_id)
        configs = {
            server.name: await mcp_factory.build(server) for server in mcp_servers
        }

        # 3. Build tool settings map
        tool_settings = {
            next(s.name for s in mcp_servers if s.id == b.mcp_server_id): b.tools
            for b in agent_mcp_servers
        }

        server_id_by_name = {server.name: str(server.id) for server in mcp_servers}
        server_names = list(configs.keys())

        # 4. Discover tools (one session per server, just to learn names/metadata).
        client = MultiServerMCPClient(configs, tool_name_prefix=True)
        results = await asyncio.gather(
            *[client.get_tools(server_name=name) for name in server_names]
        )
        tools_by_server = list(zip(server_names, results, strict=True))
        agent_tools = _assemble_agent_tools(
            tools_by_server, tool_settings, server_id_by_name
        )

        return PreparedToolset(
            client=client,
            server_names=server_names,
            tool_settings=tool_settings,
            server_id_by_name=server_id_by_name,
            interrupt_on={
                at.tool.name: True for at in agent_tools if at.requires_approval
            },
            apply_ui=apply_ui,
        )

    @classmethod
    @asynccontextmanager
    async def open(cls, prepared: PreparedToolset):
        """Stream-time phase: hold ONE live session per server and bind tools to it.

        The sessions stay open for the whole ``async with`` block, so a handle
        minted by one tool call (e.g. Metabase ``construct_query``'s
        ``query_handle``) survives to the next call (``visualize_query``). MCP tool
        execution errors (isError=True) are surfaced as ToolMessage(status="error")
        natively by langchain-mcp-adapters; transport/protocol failures raise and
        are caught globally by ToolErrorMiddleware.
        """
        async with AsyncExitStack() as stack:
            tools_by_server: list[tuple[str, list[Tool]]] = []
            for name in prepared.server_names:
                session = await stack.enter_async_context(prepared.client.session(name))
                lc_tools = await load_mcp_tools(
                    session, server_name=name, tool_name_prefix=True
                )
                tools_by_server.append((name, lc_tools))

            agent_tools = _assemble_agent_tools(
                tools_by_server, prepared.tool_settings, prepared.server_id_by_name
            )
            toolset = cls(tools=agent_tools)
            if prepared.apply_ui:
                toolset.apply_ui_metadata()
            yield toolset

    def apply_ui_metadata(self) -> None:
        """Inject UI metadata into tool coroutines.

        Call for parent agent toolsets only. Subagents don't stream UI metadata
        to the frontend, so skip this for subagent toolsets.
        """
        for t in self.tools:
            if t.ui_metadata:
                inject_ui_metadata_into_tool(t.tool, t.ui_metadata)
