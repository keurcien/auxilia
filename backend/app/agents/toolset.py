import asyncio
import logging
import re
from dataclasses import dataclass

from langchain_core.tools import Tool
from langchain_mcp_adapters.client import MultiServerMCPClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.agents.models import AgentMCPServer
from app.mcp.client.factory import MCPClientConfigFactory
from app.mcp.client.tools import inject_ui_metadata_into_tool, wrap_mcp_tool_errors
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
    async def resolve(
        cls,
        mcp_server_bindings: list[AgentMCPServer],
        db: AsyncSession,
        user_id: str,
    ) -> "Toolset":
        """Full pipeline: DB lookup -> MCP config -> fetch -> filter -> sanitize -> wrap errors -> build metadata."""
        if not mcp_server_bindings:
            return cls(tools=[])

        # 1. Load MCP server records from DB
        server_ids = [s.id for s in mcp_server_bindings]
        result = await db.execute(
            select(MCPServerDB).where(MCPServerDB.id.in_(server_ids))
        )
        mcp_servers = list(result.scalars().all())

        # 2. Build MCP client configs
        mcp_factory = MCPClientConfigFactory(db=db, user_id=user_id)
        configs = {
            server.name: await mcp_factory.build(server) for server in mcp_servers
        }

        # 3. Build tool settings map
        tool_settings = {
            next(s.name for s in mcp_servers if s.id == b.id): b.tools
            for b in mcp_server_bindings
        }

        # 4. Fetch & filter tools per server, building AgentTool objects
        client = MultiServerMCPClient(configs, tool_name_prefix=True)

        async def fetch_and_wrap(server_id: str) -> list[AgentTool]:
            lc_tools = await client.get_tools(server_name=server_id)

            settings = tool_settings.get(str(server_id))
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

            agent_tools = []
            for tool in lc_tools:
                if tool.name in allowed_names:
                    agent_tools.append(AgentTool(tool=tool, requires_approval=False))
                elif tool.name in approval_names:
                    agent_tools.append(AgentTool(tool=tool, requires_approval=True))
                # disabled or unknown tools are excluded
            return agent_tools

        results = await asyncio.gather(
            *[fetch_and_wrap(sid) for sid in configs.keys()]
        )

        agent_tools = [at for batch in results for at in batch]

        # 5. Sanitize tool names
        all_lc_tools = [at.tool for at in agent_tools]
        server_id_by_name = {server.name: str(server.id) for server in mcp_servers}
        server_names = list(server_id_by_name.keys())

        # Build UI metadata before sanitization (uses original names for prefix matching)
        for at in agent_tools:
            at.ui_metadata = _build_tool_ui_metadata(
                at.tool, server_id_by_name, server_names
            )

        _sanitize_tools_in_place(all_lc_tools)

        # 6. Wrap errors
        for at in agent_tools:
            wrap_mcp_tool_errors(at.tool)

        return cls(tools=agent_tools)

    def apply_ui_metadata(self) -> None:
        """Inject UI metadata into tool coroutines.

        Call for parent agent toolsets only. Subagents don't stream UI metadata
        to the frontend, so skip this for subagent toolsets.
        """
        for t in self.tools:
            if t.ui_metadata:
                inject_ui_metadata_into_tool(t.tool, t.ui_metadata)
