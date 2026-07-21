import asyncio
import logging
import re
from contextlib import asynccontextmanager
from dataclasses import dataclass

import anyio
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

    server_name = _resolve_server_name_from_prefixed_tool_name(tool.name, server_names)
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
        # A null map means "never synced" — treat it as no configured tools
        # rather than letting None.items() blow up the whole agent build.
        settings = tool_settings.get(str(server_id)) or {}
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


# Raised when sending on a session whose streams already closed — the request
# never left the client, so retrying it on a fresh session is safe.
_DEAD_SESSION_ERRORS = (anyio.ClosedResourceError, anyio.BrokenResourceError)


class _SessionSupervisor:
    """Opens replacement MCP sessions for servers whose transport died mid-stream.

    Each replacement is hosted in its own task (same anyio cancel-scope
    ownership rule as ``_open_sessions``) and torn down in ``close()`` at the
    end of ``Toolset.open``. ``replaced`` records which servers were
    reconnected, so ``_open_sessions`` demotes the dead primaries' teardown
    errors to warnings instead of raising them at stream end.
    """

    def __init__(self, client: MultiServerMCPClient | None):
        self._client = client
        self._stop = asyncio.Event()
        self._tasks: list[asyncio.Task] = []
        self.replaced: set[str] = set()

    async def reopen(self, name: str):
        loop = asyncio.get_running_loop()
        ready: asyncio.Future = loop.create_future()

        async def _host() -> None:
            try:
                async with self._client.session(name) as session:
                    ready.set_result(session)
                    await self._stop.wait()
            except BaseException as exc:
                if not ready.done():
                    ready.set_exception(exc)
                else:
                    raise

        self._tasks.append(asyncio.create_task(_host()))
        session = await ready
        self.replaced.add(name)
        return session

    async def close(self) -> None:
        self._stop.set()
        results = await asyncio.gather(*self._tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, BaseException) and not isinstance(
                result, asyncio.CancelledError
            ):
                logger.warning("Replacement MCP session teardown failed: %r", result)


class ReconnectingSession:
    """Per-server ``ClientSession`` proxy that survives a dead transport.

    All of a server's tools are bound to this proxy (not to the raw session),
    so when the transport dies mid-run — the server drops the connection, the
    GET stream flaps — the next ``call_tool`` reopens the session once and
    retries, instead of every remaining call failing on the same corpse.

    ``list_tools`` gets the same treatment so tool discovery
    (``Toolset.open`` → ``load_mcp_tools``) survives a transport that dies
    right after the session opened, instead of aborting the whole run at
    setup.

    Only ``_DEAD_SESSION_ERRORS`` are retried: they mean the request was never
    sent, so at-most-once execution is preserved. Mid-flight failures (e.g.
    ``McpError`` "Connection closed") are NOT retried — the call may have
    executed server-side; they surface as error ToolMessages via
    ToolErrorMiddleware, and the next call on this server reconnects.
    """

    def __init__(self, name: str, session, supervisor: _SessionSupervisor):
        self._session = session
        self._name = name
        self._generation = 0
        self._supervisor = supervisor
        self._lock = asyncio.Lock()

    def __getattr__(self, attr: str):
        # Rest of the session API hits the current live session directly,
        # without retry.
        return getattr(self._session, attr)

    async def call_tool(self, *args, **kwargs):
        return await self._retry_on_dead_session("call_tool", *args, **kwargs)

    async def list_tools(self, *args, **kwargs):
        return await self._retry_on_dead_session("list_tools", *args, **kwargs)

    async def _retry_on_dead_session(self, method: str, *args, **kwargs):
        session, generation = self._session, self._generation
        try:
            return await getattr(session, method)(*args, **kwargs)
        except _DEAD_SESSION_ERRORS as exc:
            session = await self._reconnect(generation, exc)
            return await getattr(session, method)(*args, **kwargs)

    async def _reconnect(self, seen_generation: int, cause: BaseException):
        """Reopen once per dead session, even under concurrent callers."""
        async with self._lock:
            if self._generation == seen_generation:
                logger.warning(
                    "MCP session '%s' is dead (%s); opening a replacement",
                    self._name,
                    type(cause).__name__,
                )
                self._session = await self._supervisor.reopen(self._name)
                self._generation += 1
            return self._session


@asynccontextmanager
async def _open_sessions(
    client: MultiServerMCPClient | None,
    server_names: list[str],
    *,
    replaced: set[str] | None = None,
):
    """Open one live MCP session per server, concurrently.

    Each session's context manager is entered AND exited inside a dedicated
    host task: the streamable-HTTP transport is built on anyio cancel scopes,
    which must exit in the task that entered them — entering the contexts from
    a ``gather`` onto a shared exit stack would crash at teardown.

    ``replaced`` (shared with the ``_SessionSupervisor``) names servers whose
    primary session died and was replaced mid-stream: their teardown errors
    are expected, so they are logged instead of raised.
    """
    if not server_names:
        yield {}
        return

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    ready: dict[str, asyncio.Future] = {n: loop.create_future() for n in server_names}

    async def _host(name: str) -> None:
        try:
            async with client.session(name) as session:
                ready[name].set_result(session)
                await stop.wait()
        except BaseException as exc:
            if not ready[name].done():
                ready[name].set_exception(exc)
            else:
                raise

    tasks = [asyncio.create_task(_host(n)) for n in server_names]

    async def _teardown() -> list:
        stop.set()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for f in ready.values():  # retrieve to silence "never retrieved" warnings
            if f.done() and not f.cancelled():
                f.exception()
        return results

    try:
        sessions = {n: await ready[n] for n in server_names}
        yield sessions
    except BaseException:
        await _teardown()
        raise
    else:
        for name, result in zip(server_names, await _teardown(), strict=True):
            if not isinstance(result, BaseException) or isinstance(
                result, asyncio.CancelledError
            ):
                continue
            if replaced and name in replaced:
                logger.warning(
                    "Dead MCP session '%s' teardown failed after it was replaced: %r",
                    name,
                    result,
                )
                continue
            raise result


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
        """Build-time phase: DB lookup -> configs -> interrupt_on. No network.

        All DB access happens here (request scope). ``interrupt_on`` is derived
        from the persisted per-agent tool map (synced at connect/save time), so
        no MCP session is opened — live discovery happens once, in :meth:`open`.
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

        # 4. Derive interrupt_on from the persisted tool map — the synced
        #    settings already hold every tool name, so no session is opened.
        #    Live names are prefixed ``{server_name}_{tool}`` then sanitized;
        #    we replay that here. Caveat: the ``_2`` dedup suffixes applied at
        #    open time on sanitize collisions can't be predicted, so a
        #    colliding needs_approval tool would miss its gate — collisions
        #    require characters outside [a-zA-Z0-9_-] in server/tool names.
        client = MultiServerMCPClient(configs, tool_name_prefix=True)
        interrupt_on: dict[str, bool] = {}
        for name in server_names:
            settings = tool_settings.get(name) or {}
            for tool_name, status in settings.items():
                if status == "needs_approval":
                    interrupt_on[sanitize_tool_name(f"{name}_{tool_name}")] = True

        return PreparedToolset(
            client=client,
            server_names=server_names,
            tool_settings=tool_settings,
            server_id_by_name=server_id_by_name,
            interrupt_on=interrupt_on,
            apply_ui=apply_ui,
        )

    @classmethod
    @asynccontextmanager
    async def open(cls, prepared: PreparedToolset):
        """Stream-time phase: hold ONE live session per server and bind tools to it.

        The sessions stay open for the whole ``async with`` block, so a handle
        minted by one tool call (e.g. Metabase ``construct_query``'s
        ``query_handle``) survives to the next call (``visualize_query``). Tools
        are bound to a ``ReconnectingSession`` proxy, so a session whose
        transport dies mid-run is reopened on the next call instead of failing
        every remaining call. MCP tool execution errors (isError=True) are
        surfaced as ToolMessage(status="error") natively by
        langchain-mcp-adapters; transport/protocol failures raise and are
        caught globally by ToolErrorMiddleware.
        """
        supervisor = _SessionSupervisor(prepared.client)
        async with _open_sessions(
            prepared.client, prepared.server_names, replaced=supervisor.replaced
        ) as sessions:
            try:
                proxies = {
                    name: ReconnectingSession(name, sessions[name], supervisor)
                    for name in prepared.server_names
                }
                results = await asyncio.gather(
                    *[
                        load_mcp_tools(
                            proxies[name], server_name=name, tool_name_prefix=True
                        )
                        for name in prepared.server_names
                    ]
                )
                tools_by_server = list(zip(prepared.server_names, results, strict=True))

                agent_tools = _assemble_agent_tools(
                    tools_by_server, prepared.tool_settings, prepared.server_id_by_name
                )
                toolset = cls(tools=agent_tools)
                if prepared.apply_ui:
                    toolset.apply_ui_metadata()
                yield toolset
            finally:
                await supervisor.close()

    def apply_ui_metadata(self) -> None:
        """Inject UI metadata into tool coroutines.

        Call for parent agent toolsets only. Subagents don't stream UI metadata
        to the frontend, so skip this for subagent toolsets.
        """
        for t in self.tools:
            if t.ui_metadata:
                inject_ui_metadata_into_tool(t.tool, t.ui_metadata)
