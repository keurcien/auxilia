import logging
import re
import warnings
from collections.abc import Collection, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import cast
from uuid import UUID

from fastmcp.client.group import ClientGroup
from langchain_core._api import LangChainBetaWarning
from langchain_core.tools import BaseTool
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.models import AgentMCPServerBase
from app.mcp.client.connection import ConnectionSpec, build_client
from app.mcp.client.connectivity import CredentialCache, resolve_connection
from app.mcp.client.exceptions import as_oauth_required
from app.mcp.client.tools import bound_tool_artifact
from app.mcp.servers.models import MCPServerDB
from app.mcp.servers.repository import MCPServerRepository


# `langchain.mcp` is in beta and says so once per process at import; the
# module is the one adapter this runtime uses, so the notice is noise here.
with warnings.catch_warnings():
    warnings.simplefilter("ignore", LangChainBetaWarning)
    from langchain.mcp import MCPAdapter


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


def _sanitize_tools_in_place(tools: list[BaseTool]) -> dict[str, str]:
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


def _extract_mcp_app_resource_uri(tool: BaseTool) -> str | None:
    """The MCP-app resource URI a tool declares, if any.

    `langchain.mcp` keeps a tool's provenance under ``metadata["mcp"]``: the
    server's ``_meta`` sits at ``metadata["mcp"]["tool"]["_meta"]``, and MCP
    Apps put the widget's URI at ``_meta["ui"]["resourceUri"]`` (older
    servers under the extension identifier instead of ``ui``).
    """
    metadata = getattr(tool, "metadata", None)
    if not isinstance(metadata, dict):
        return None

    mcp_meta = metadata.get("mcp")
    if not isinstance(mcp_meta, dict):
        return None
    tool_meta = mcp_meta.get("tool")
    if not isinstance(tool_meta, dict):
        return None
    raw_meta = tool_meta.get("_meta")
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


def _build_tool_ui_metadata(tool: BaseTool, server_id: str) -> dict[str, str] | None:
    resource_uri = _extract_mcp_app_resource_uri(tool)
    if not resource_uri:
        return None
    return {
        "mcp_app_resource_uri": resource_uri,
        "mcp_server_id": server_id,
    }


@dataclass
class AgentTool:
    """A resolved MCP tool with its approval status and UI metadata."""

    tool: BaseTool
    requires_approval: bool = False
    ui_metadata: dict[str, str] | None = None


@dataclass
class PreparedToolset:
    """DB-derived spec needed to (re)bind MCP tools onto live connections.

    Built at agent-build time (request scope, with the request DB), it carries
    everything required to connect and assemble tools later during the
    streaming response — without touching the DB. ``interrupt_on`` is computed
    here so HITL middleware can be wired at build time.
    """

    connections: dict[str, ConnectionSpec]  # keyed by MCP server name, fixed order
    tool_settings: dict[str, dict]
    server_id_by_name: dict[str, str]
    interrupt_on: dict[str, bool]  # sanitized tool name -> True
    apply_ui: bool

    @property
    def server_names(self) -> list[str]:
        return list(self.connections)


def _assemble_agent_tools(
    tools_by_server: list[tuple[str, list[BaseTool]]],
    tool_settings: dict[str, dict],
    server_id_by_name: dict[str, str],
) -> list[AgentTool]:
    """Filter -> build UI metadata -> sanitize.

    ``tools_by_server`` must be in a FIXED server order (and each server's
    tools in the server's order) across runs: ``_sanitize_tools_in_place`` is
    order-sensitive (dedup suffixes), so identical ordering is what guarantees
    the sanitized names computed at build (for ``interrupt_on``) match the
    names of the live tools opened at stream time.
    """
    agent_tools: list[AgentTool] = []
    for server_name, lc_tools in tools_by_server:
        # A null map means "never synced" — treat it as no configured tools
        # rather than letting None.items() blow up the whole agent build.
        settings = tool_settings.get(server_name) or {}
        allowed_names = {
            f"{server_name}_{t}"
            for t, status in settings.items()
            if status == "always_allow"
        }
        approval_names = {
            f"{server_name}_{t}"
            for t, status in settings.items()
            if status == "needs_approval"
        }
        server_id = server_id_by_name[server_name]
        for tool in lc_tools:
            if tool.name in allowed_names:
                requires_approval = False
            elif tool.name in approval_names:
                requires_approval = True
            else:
                continue  # disabled or unknown tools are excluded
            agent_tools.append(
                AgentTool(
                    tool=tool,
                    requires_approval=requires_approval,
                    ui_metadata=_build_tool_ui_metadata(tool, server_id),
                )
            )

    _sanitize_tools_in_place([at.tool for at in agent_tools])
    return agent_tools


class MCPResolutionScope:
    """Server rows and credentials read once for a whole run graph.

    `Toolset.prepare` runs once per agent, and a run graph is a parent plus its
    direct subagents — which routinely bind the same MCP servers. Resolved per
    agent, that was one `list_by_ids` *and* one credential read per agent per
    server: O(N) round-trips before the first token, for rows a single `IN`
    query covers (design review §2.2).

    Only reads are shared. Each agent still gets its own connection spec,
    because an OAuth spec carries a stateful `WebOAuthClientProvider` and the
    parent's and subagents' sessions are opened concurrently.
    """

    def __init__(self, db: AsyncSession, user_id: str):
        self._repo = MCPServerRepository(db)
        self._user_id = user_id
        self._rows: dict[UUID, MCPServerDB] = {}
        self._credentials = CredentialCache()

    @classmethod
    async def build(
        cls,
        bindings: Sequence[AgentMCPServerBase],
        db: AsyncSession,
        user_id: str,
    ) -> "MCPResolutionScope":
        """Preload every server the graph's `bindings` name, in one query."""
        scope = cls(db, user_id)
        await scope.load([b.mcp_server_id for b in bindings])
        return scope

    async def load(self, server_ids: Collection[UUID]) -> None:
        missing = [sid for sid in dict.fromkeys(server_ids) if sid not in self._rows]
        for server in await self._repo.list_by_ids(missing):
            self._rows[server.id] = server

    def servers(self, server_ids: Sequence[UUID]) -> list[MCPServerDB]:
        """The rows behind `server_ids`, skipping ids with no server left."""
        rows = [
            self._rows[sid] for sid in dict.fromkeys(server_ids) if sid in self._rows
        ]
        return rows

    async def connection(self, server: MCPServerDB) -> ConnectionSpec:
        """This agent's connection spec for `server`, sharing the decrypted key."""
        return await resolve_connection(
            server, self._user_id, self._repo, credentials=self._credentials
        )


class Toolset:
    """Resolved, ready-to-use tools from MCP servers."""

    def __init__(self, tools: list[AgentTool]):
        self.tools = tools

    @property
    def all(self) -> list[BaseTool]:
        return [t.tool for t in self.tools]

    @property
    def interrupt_on(self) -> dict[str, bool]:
        return {t.tool.name: True for t in self.tools if t.requires_approval}

    @classmethod
    async def prepare(
        cls,
        agent_mcp_servers: Sequence[AgentMCPServerBase],
        db: AsyncSession,
        user_id: str,
        *,
        apply_ui: bool,
        scope: MCPResolutionScope | None = None,
    ) -> PreparedToolset:
        """Build-time phase: DB lookup -> connection specs -> interrupt_on. No network.

        Typed on ``AgentMCPServerBase`` — the column set shared by the binding
        row and its response DTO — because only ``mcp_server_id`` and ``tools``
        are read here. The run path passes rows straight from ``RunSpec``; the
        API paths pass their DTOs.

        All DB access happens here (request scope). ``interrupt_on`` is derived
        from the persisted per-agent tool map (synced at connect/save time), so
        no MCP session is opened — live discovery happens once, in :meth:`open`.

        ``scope`` lets a caller resolving several agents (a run graph) share one
        batched server read across them; without it this agent gets a scope of
        its own and the reads stay per-agent.
        """
        empty = PreparedToolset(
            connections={},
            tool_settings={},
            server_id_by_name={},
            interrupt_on={},
            apply_ui=apply_ui,
        )
        if not agent_mcp_servers:
            return empty

        # 1. Load MCP server records from DB
        server_ids = [s.mcp_server_id for s in agent_mcp_servers]
        if scope is None:
            scope = MCPResolutionScope(db, user_id)
            await scope.load(server_ids)
        mcp_servers = scope.servers(server_ids)

        # 2. Resolve each server's connection (auth to Redis/header values — no
        #    live SQL handle is retained, so the specs are safe to use later
        #    during streaming, after the request DB session has closed).
        connections = {
            server.name: await scope.connection(server) for server in mcp_servers
        }

        # 3. Build tool settings map
        tool_settings = {
            next(s.name for s in mcp_servers if s.id == b.mcp_server_id): b.tools
            for b in agent_mcp_servers
        }

        server_id_by_name = {server.name: str(server.id) for server in mcp_servers}

        # 4. Derive interrupt_on from the persisted tool map — the synced
        #    settings already hold every tool name, so no session is opened.
        #    Live names are prefixed ``{server_name}_{tool}`` then sanitized;
        #    we replay that here. Caveat: the ``_2`` dedup suffixes applied at
        #    open time on sanitize collisions can't be predicted, so a
        #    colliding needs_approval tool would miss its gate — collisions
        #    require characters outside [a-zA-Z0-9_-] in server/tool names.
        interrupt_on: dict[str, bool] = {}
        for name in connections:
            settings = tool_settings.get(name) or {}
            for tool_name, status in settings.items():
                if status == "needs_approval":
                    interrupt_on[sanitize_tool_name(f"{name}_{tool_name}")] = True

        return PreparedToolset(
            connections=connections,
            tool_settings=tool_settings,
            server_id_by_name=server_id_by_name,
            interrupt_on=interrupt_on,
            apply_ui=apply_ui,
        )

    @classmethod
    @asynccontextmanager
    async def open(cls, prepared: PreparedToolset):
        """Stream-time phase: hold ONE live connection per server and bind tools to it.

        One FastMCP ``Client`` per server, grouped in a ``ClientGroup`` (which
        namespaces tools ``{server}_{tool}``) and adapted by ``langchain.mcp``.
        The adapter's context is held for the whole ``async with`` block, so a
        handle minted by one tool call (e.g. Metabase ``construct_query``'s
        ``query_handle``) survives to the next call (``visualize_query``); each
        tool re-enters the same client per call, which is a reference-counted
        no-op while the context is held.

        MCP tool execution errors (``isError=True``) reach the model as
        ``ToolMessage(status="error")`` natively; transport/protocol failures
        raise and are caught by ``ToolErrorMiddleware``. A transport that dies
        mid-run fails that server's remaining calls the same way — the client
        does not reconnect while its context is held.
        """
        if not prepared.connections:
            toolset = cls(tools=[])
            toolset.bound_artifacts(ui=prepared.apply_ui)
            yield toolset
            return

        clients = {
            name: build_client(spec) for name, spec in prepared.connections.items()
        }
        adapter = MCPAdapter(ClientGroup(clients))
        # The adapter clones a group into a group (it arms each member for
        # elicitation), so `adapter.client` is the `ClientGroup` we route on.
        group = cast(ClientGroup, adapter.client)
        try:
            async with adapter:
                lc_tools = await adapter.list_tools()
                # Tools come back namespaced and flat; regroup them per server
                # (in the prepared order) for the settings filter.
                by_server: dict[str, list[BaseTool]] = {
                    name: [] for name in prepared.server_names
                }
                for tool in lc_tools:
                    route = await group.resolve_tool(tool.name)
                    by_server[route.server_name].append(tool)

                agent_tools = _assemble_agent_tools(
                    list(by_server.items()),
                    prepared.tool_settings,
                    prepared.server_id_by_name,
                )
                toolset = cls(tools=agent_tools)
                toolset.bound_artifacts(ui=prepared.apply_ui)
                yield toolset
        except BaseException as exc:
            # The MCP seam for the run path (the other is
            # `connection.open_client`): a server that needs authorization
            # fails its connect inside the group, and FastMCP reports that as
            # the cause of its own "failed to connect" error. Unwrap it so the
            # run worker can recognise it — nothing else is altered.
            oauth = as_oauth_required(exc)
            if oauth is not None and oauth is not exc:
                raise oauth from exc
            raise

    def bound_artifacts(self, *, ui: bool) -> None:
        """Apply the per-tool artifact policy (`app/mcp/client/tools.py`) to
        every tool: app tools keep and stamp their structured content, the rest
        lose it. `ui` is True for the parent agent only — subagents never
        stream widgets to the frontend, so their app tools are bounded like any
        other.
        """
        for t in self.tools:
            bound_tool_artifact(t.tool, t.ui_metadata if ui else None)
