import asyncio
import logging
import re
import warnings
from collections.abc import Collection, Sequence
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
from uuid import UUID

from fastmcp.client import Client
from langchain_core._api import LangChainBetaWarning
from langchain_core.tools import BaseTool
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.models import AgentMCPServerBase
from app.artifacts.gallery import ImagePreviewSource
from app.database_connections.tools import DBHUB_MANAGED_BY, allowed_tool_names
from app.exceptions import root_cause
from app.mcp.client.connection import ConnectionSpec, build_client
from app.mcp.client.connectivity import (
    CredentialCache,
    probe_authorization,
    resolve_connection,
)
from app.mcp.client.exceptions import as_oauth_required
from app.mcp.client.tools import (
    bound_tool_artifact,
    normalize_mcp_tool_schema,
    sanitize_mcp_property_keys,
)
from app.mcp.servers.models import MCPServerDB
from app.mcp.servers.repository import MCPServerRepository
from app.memories.constants import MEMORY_TOOL_NAMES


# `langchain.mcp` is in beta and says so once per process at import; the
# module is the one adapter this runtime uses, so the notice is noise here.
with warnings.catch_warnings():
    warnings.simplefilter("ignore", LangChainBetaWarning)
    from langchain.mcp import MCPAdapter


logger = logging.getLogger(__name__)

MCP_OPEN_TIMEOUT_SECONDS = 15
MAX_SERVER_INSTRUCTIONS_CHARS = 4_000


_VALID_TOOL_NAME_CHARS = re.compile(r"[^a-zA-Z0-9_-]")
_MAX_TOOL_NAME_LENGTH = 128


def sanitize_tool_name(name: str) -> str:
    sanitized = _VALID_TOOL_NAME_CHARS.sub("_", name).strip("_")
    if not sanitized:
        sanitized = "tool"
    if len(sanitized) > _MAX_TOOL_NAME_LENGTH:
        sanitized = sanitized[:_MAX_TOOL_NAME_LENGTH].rstrip("_")
    return sanitized or "tool"


def sanitize_external_tool_name(name: str) -> str:
    sanitized = sanitize_tool_name(name)
    if sanitized in MEMORY_TOOL_NAMES:
        return f"mcp_{sanitized}"
    return sanitized


def _sanitize_tools_in_place(tools: list[BaseTool]) -> dict[str, str]:
    used_names: set[str] = set()
    name_map: dict[str, str] = {}

    for tool in tools:
        original_name = tool.name
        base_name = sanitize_external_tool_name(original_name)
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
    disabled_tools: dict[str, set[str]] = field(default_factory=dict)
    managed_allowed_tools: dict[str, set[str]] = field(default_factory=dict)
    server_description_by_name: dict[str, str | None] = field(default_factory=dict)
    server_instructions_by_name: dict[str, str] = field(default_factory=dict)
    image_previews: dict[str, ImagePreviewSource] = field(default_factory=dict)

    @property
    def server_names(self) -> list[str]:
        return list(self.connections)

    @property
    def mcp_context_prompt(self) -> str | None:
        """One compact capability index for the model's system prompt."""
        if not self.server_description_by_name:
            return None

        servers: list[str] = []
        for name in self.connections:
            description = self.server_description_by_name.get(name)
            compact_description = " ".join(description.split()) if description else ""
            instructions = self.server_instructions_by_name.get(name)
            compact_instructions = (
                " ".join(instructions.split())[:MAX_SERVER_INSTRUCTIONS_CHARS]
                if instructions
                else ""
            )
            details = []
            if compact_description:
                details.append(compact_description)
            if compact_instructions:
                details.append(f"Server instructions: {compact_instructions}")
            servers.append(f"- {name}: {' '.join(details)}" if details else f"- {name}")

        return (
            "MCP servers available to this agent:\n"
            + "\n".join(servers)
            + "\nUse these descriptions to identify relevant tools. Before saying "
            "that a capability or data source is unavailable, check whether one "
            "of these servers provides it."
        )


def _assemble_agent_tools(
    tools_by_server: list[tuple[str, list[BaseTool]]],
    tool_settings: dict[str, dict],
    disabled_tools: dict[str, set[str]],
    managed_allowed_tools: dict[str, set[str]],
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
        globally_disabled_names = {
            f"{server_name}_{name}" for name in disabled_tools.get(server_name, set())
        }
        managed_allowed_names = {
            f"{server_name}_{name}"
            for name in managed_allowed_tools.get(server_name, set())
        }
        is_managed = server_name in managed_allowed_tools
        server_id = server_id_by_name[server_name]
        for tool in lc_tools:
            if tool.name in globally_disabled_names:
                continue
            if is_managed and tool.name not in managed_allowed_names:
                continue
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

    def __init__(self, db: AsyncSession, user_id: str, workspace_id: UUID):
        self._repo = MCPServerRepository(db, workspace_id)
        self._user_id = user_id
        self._workspace_id = workspace_id
        self._rows: dict[UUID, MCPServerDB] = {}
        self._credentials = CredentialCache()

    @classmethod
    async def build(
        cls,
        bindings: Sequence[AgentMCPServerBase],
        db: AsyncSession,
        user_id: str,
        workspace_id: UUID,
        *,
        authorized_only: bool = False,
    ) -> MCPResolutionScope:
        """Preload the graph's servers, optionally omitting unauthorized ones.

        Runs use ``authorized_only`` so an optional personal binding (OAuth,
        or an API key / headers the user has not entered) cannot prevent the
        agent from answering with its other tools. The authorization probe is
        user-scoped; no credential is shared.
        """
        scope = cls(db, user_id, workspace_id)
        await scope.load([b.mcp_server_id for b in bindings])
        if authorized_only:
            try:
                authorization = await probe_authorization(
                    scope._rows.values(),
                    user_id,
                    workspace_id,
                    repository=scope._repo,
                )
            except Exception:  # noqa: BLE001 — optional MCP auth must not block the LLM
                logger.warning(
                    "Could not probe MCP authorization; resolving servers individually",
                    exc_info=True,
                )
            else:
                scope._rows = {
                    server_id: server
                    for server_id, server in scope._rows.items()
                    if authorization.get(server_id, True)
                }
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
            server,
            self._user_id,
            self._workspace_id,
            self._repo,
            credentials=self._credentials,
        )


class Toolset:
    """Resolved, ready-to-use tools from MCP servers."""

    def __init__(
        self, tools: list[AgentTool], clients: dict[str, Client] | None = None
    ):
        self.tools = tools
        # Live sessions by server name, open for the run; image galleries read
        # MCP resources through them with the run's own credentials.
        self.clients = clients or {}

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
        workspace_id: UUID,
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
            disabled_tools={},
            managed_allowed_tools={},
            server_id_by_name={},
            interrupt_on={},
            apply_ui=apply_ui,
        )
        if not agent_mcp_servers:
            return empty

        # 1. Load MCP server records from DB
        server_ids = [s.mcp_server_id for s in agent_mcp_servers]
        if scope is None:
            scope = MCPResolutionScope(db, user_id, workspace_id)
            await scope.load(server_ids)
        mcp_servers = scope.servers(server_ids)

        # 2. Resolve each server's connection (auth to Redis/header values — no
        #    live SQL handle is retained, so the specs are safe to use later
        #    during streaming, after the request DB session has closed).
        connections: dict[str, ConnectionSpec] = {}
        for server in mcp_servers:
            try:
                connections[server.name] = await scope.connection(server)
            except Exception:  # noqa: BLE001 — one MCP server is an optional capability
                logger.warning(
                    "Omitting MCP server %s while resolving its connection",
                    server.name,
                    exc_info=True,
                )

        mcp_servers = [server for server in mcp_servers if server.name in connections]

        # 3. Build tool settings map
        server_name_by_id = {server.id: server.name for server in mcp_servers}
        tool_settings = {
            server_name_by_id[b.mcp_server_id]: b.tools
            for b in agent_mcp_servers
            if b.mcp_server_id in server_name_by_id
        }
        disabled_tools = {
            server.name: set(server.disabled_tools) for server in mcp_servers
        }
        managed_allowed_tools = {
            server.name: (
                allowed_tool_names(server.managed_resource_id)
                if server.managed_resource_id is not None
                else set()
            )
            for server in mcp_servers
            if server.managed_by == DBHUB_MANAGED_BY
        }

        server_id_by_name = {server.name: str(server.id) for server in mcp_servers}
        server_description_by_name = {
            server.name: server.description for server in mcp_servers
        }
        preview_rows = await MCPServerRepository(db, workspace_id).list_image_previews(
            list(server_name_by_id)
        )
        image_previews = {
            server_name_by_id[row.mcp_server_id]: ImagePreviewSource.from_row(row)
            for row in preview_rows
        }

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
                if status == "needs_approval" and tool_name not in disabled_tools.get(
                    name, set()
                ):
                    interrupt_on[sanitize_external_tool_name(f"{name}_{tool_name}")] = (
                        True
                    )

        return PreparedToolset(
            connections=connections,
            tool_settings=tool_settings,
            disabled_tools=disabled_tools,
            managed_allowed_tools=managed_allowed_tools,
            server_id_by_name=server_id_by_name,
            server_description_by_name=server_description_by_name,
            image_previews=image_previews,
            interrupt_on=interrupt_on,
            apply_ui=apply_ui,
        )

    @classmethod
    @asynccontextmanager
    async def open(cls, prepared: PreparedToolset):
        """Open each available server and bind only its usable tools.

        OAuth is optional at execution time. The authorization probe used while
        preparing the graph cheaply removes servers with no stored credential;
        this live handshake is the authoritative backstop for revoked or expired
        credentials. Any server that cannot open or list its tools is omitted
        without affecting the other servers, so one unavailable integration
        cannot prevent the agent from answering.

        Each adapter's context is held for the whole ``async with`` block, so a
        handle minted by one tool call (e.g. Metabase ``construct_query``'s
        ``query_handle``) survives to the next call. Tools are namespaced here
        as ``{server}_{tool}``, matching the previous ``ClientGroup`` contract.

        MCP tool execution errors (``isError=True``) reach the model as
        ``ToolMessage(status="error")`` natively; transport/protocol failures
        raise and are caught by ``ToolErrorMiddleware``. The failing call is
        not retried automatically because it may have caused a write, but the
        next call reconnects if the remote session died.
        """
        if not prepared.connections:
            toolset = cls(tools=[])
            toolset.bound_artifacts(ui=prepared.apply_ui)
            yield toolset
            return

        async with AsyncExitStack() as stack:
            unavailable_servers: set[str] = set()
            clients: dict[str, Client] = {}

            async def open_server(
                server_name: str, spec: ConnectionSpec
            ) -> tuple[str, list[BaseTool]] | None:
                prepared.server_instructions_by_name.pop(server_name, None)
                client = build_client(spec)
                adapter = MCPAdapter(client)
                entered = False
                try:
                    async with asyncio.timeout(MCP_OPEN_TIMEOUT_SECONDS):
                        await adapter.__aenter__()
                        entered = True
                        if client.instructions and client.instructions.strip():
                            prepared.server_instructions_by_name[server_name] = (
                                client.instructions.strip()
                            )
                        lc_tools = await adapter.list_tools()
                except BaseException as exc:
                    if entered:
                        try:
                            await adapter.__aexit__(type(exc), exc, exc.__traceback__)
                        except Exception:  # noqa: BLE001 — cleanup stays best-effort
                            logger.warning(
                                "Failed to close unavailable MCP server %s",
                                server_name,
                                exc_info=True,
                            )
                    cause = root_cause(exc)
                    if not isinstance(cause, Exception):
                        raise
                    if as_oauth_required(exc) is not None:
                        logger.info(
                            "Omitting unauthorized OAuth MCP server %s from run",
                            server_name,
                        )
                    else:
                        logger.warning(
                            "Omitting unavailable MCP server %s from run: %s",
                            server_name,
                            str(cause) or type(cause).__name__,
                            exc_info=(type(exc), exc, exc.__traceback__),
                        )
                    unavailable_servers.add(server_name)
                    return None

                stack.push_async_exit(adapter)
                # The adapter connects a clone of `client`, not `client` itself.
                if isinstance(adapter.client, Client):
                    clients[server_name] = adapter.client
                for tool in lc_tools:
                    renamed_keys = sanitize_mcp_property_keys(tool)
                    if renamed_keys:
                        logger.warning(
                            "Renamed invalid property keys %s in MCP tool schema %s/%s",
                            ", ".join(renamed_keys),
                            server_name,
                            tool.name,
                        )
                    bounds_changed, dangling_refs = normalize_mcp_tool_schema(tool)
                    if bounds_changed:
                        logger.warning(
                            "Normalized legacy exclusive bounds in MCP tool schema "
                            "%s/%s",
                            server_name,
                            tool.name,
                        )
                    if dangling_refs:
                        logger.warning(
                            "Removed unresolved references %s from MCP tool schema "
                            "%s/%s",
                            ", ".join(dangling_refs),
                            server_name,
                            tool.name,
                        )
                    original_description = tool.description.strip()
                    tool.metadata = {
                        **(tool.metadata if isinstance(tool.metadata, dict) else {}),
                        "auxilia_mcp_server": server_name,
                    }
                    tool.description = f"MCP server: {server_name}."
                    if original_description:
                        tool.description += f"\n\n{original_description}"
                    tool.name = f"{server_name}_{tool.name}"
                return server_name, lc_tools

            opened = await asyncio.gather(
                *(
                    open_server(server_name, spec)
                    for server_name, spec in prepared.connections.items()
                )
            )
            tools_by_server = [result for result in opened if result is not None]

            for server_name in unavailable_servers:
                prepared.connections.pop(server_name, None)
                prepared.server_description_by_name.pop(server_name, None)
                prepared.server_instructions_by_name.pop(server_name, None)

            agent_tools = _assemble_agent_tools(
                tools_by_server,
                prepared.tool_settings,
                prepared.disabled_tools,
                prepared.managed_allowed_tools,
                prepared.server_id_by_name,
            )
            toolset = cls(tools=agent_tools, clients=clients)
            toolset.bound_artifacts(ui=prepared.apply_ui)
            yield toolset

    def bound_artifacts(self, *, ui: bool) -> None:
        """Apply the per-tool artifact policy (`app/mcp/client/tools.py`) to
        every tool: app tools keep and stamp their structured content, the rest
        lose it. `ui` is True for the parent agent only — subagents never
        stream widgets to the frontend, so their app tools are bounded like any
        other.
        """
        for t in self.tools:
            bound_tool_artifact(t.tool, t.ui_metadata if ui else None)
