import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass

import httpx
from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage
from langchain_core.tools import StructuredTool, Tool
from langchain_deepseek import ChatDeepSeek
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command
from mcp.types import CallToolResult
from mcp.types import Tool as MCPTool
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.adapters.message_adapter import (
    extract_approved_tool_call_ids,
    extract_commands,
    extract_rejected_tool_calls,
    to_langchain_message,
)
from app.adapters.stream.adapter import AISDKStreamAdapter, SlackStreamAdapter
from app.agents.service import AgentService
from app.agents.settings import agent_settings
from app.database import get_psycopg_conn_string
from app.integrations.langfuse.callback import langfuse_callback_handler
from app.mcp.client.factory import MCPClientConfigFactory
from app.mcp.client.storage import TokenStorageFactory
from app.mcp.client.tools import inject_ui_metadata_into_tool, wrap_mcp_tool_errors
from app.mcp.servers.models import MCPServerDB
from app.mcp.servers.router import get_mcp_server_api_key
from app.model_providers.settings import model_provider_settings
from app.models.message import Message
from app.threads.models import ThreadDB
from app.utils.timer import RequestTimer

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Raw HTTP tool listing — bypasses the MCP ClientSession / GET SSE stream
# ---------------------------------------------------------------------------
# Some servers (e.g. Google Sheets MCP on Cloud Run) implement the 2025-03-26
# Streamable HTTP spec in a way where they only open the GET SSE stream when
# they have a message to push.  The MCP SDK opens a GET stream after
# notifications/initialized, then sends tools/list.  The server returns
# 202 Accepted for tools/list (intending to push the result via GET stream),
# but the GET stream HTTP response is held by the server until it has the
# tools/list result ready — creating a race that results in ~15 s delays.
#
# By listing tools with plain HTTP (no GET stream), the server must respond
# inline and the call completes in <1 s — matching the MCP Inspector and
# other raw clients.  Actual tool *invocations* still go through the full
# SDK session so that streaming / progress notifications work correctly.

def _parse_mcp_response_body(response: httpx.Response) -> dict:
    """Parse a synchronous-style MCP response (JSON or single-event SSE).

    Needed because servers that return 202 Accepted and intend to push the result
    via GET SSE sometimes fall back to inline SSE delivery when no GET stream is open.

    Upstream: https://github.com/modelcontextprotocol/python-sdk/issues/1661
    """
    content_type = response.headers.get("content-type", "")
    if "text/event-stream" in content_type:
        last: dict = {}
        for line in response.text.splitlines():
            if line.startswith("data:"):
                raw = line[len("data:"):].strip()
                if raw:
                    try:
                        last = json.loads(raw)
                    except json.JSONDecodeError:
                        pass
        return last
    return response.json()


async def _raw_list_mcp_tools(connection: dict) -> list[MCPTool]:
    """Fetch MCP tool definitions via plain HTTP without a GET SSE stream.

    Args:
        connection: A connection config dict as produced by MCPClientConfigFactory,
                    e.g. ``{"transport": "http", "url": "...", "headers": {...}}``
                    or   ``{"transport": "http", "url": "...", "auth": <httpx.Auth>}``.

    Returns:
        List of raw MCP Tool objects (not yet converted to LangChain tools).

    Upstream:
        https://github.com/modelcontextprotocol/python-sdk/issues/1661
            SDK does not handle 202 Accepted responses — hangs waiting for a GET
            SSE event that the server only delivers once the stream is open.
        https://github.com/modelcontextprotocol/python-sdk/issues/1053
            Streamable HTTP transport hangs when connecting to a server on Cloud Run,
            which is the exact deployment scenario that triggered this workaround.
    """
    url: str = connection["url"]
    extra_headers: dict = connection.get("headers") or {}
    auth: httpx.Auth | None = connection.get("auth")

    request_headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        **extra_headers,
    }

    async with httpx.AsyncClient(
        auth=auth,
        follow_redirects=True,
        timeout=httpx.Timeout(30.0, read=60.0),
    ) as client:
        # 1. Initialise.
        init_resp = await client.post(url, headers=request_headers, json={
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "auxilia", "version": "1.0"},
            },
            "jsonrpc": "2.0",
            "id": 0,
        })
        init_resp.raise_for_status()

        session_id = init_resp.headers.get("mcp-session-id")
        session_headers = dict(request_headers)
        if session_id:
            session_headers["mcp-session-id"] = session_id

        init_data = _parse_mcp_response_body(init_resp)
        negotiated = (init_data.get("result", {}).get("protocolVersion")
                      if init_data else None)
        if negotiated:
            session_headers["mcp-protocol-version"] = negotiated

        # 2. Notify the server that initialisation is done.
        await client.post(url, headers=session_headers, json={
            "method": "notifications/initialized",
            "jsonrpc": "2.0",
        })

        # 3. List tools (paginated).
        all_tools: list[MCPTool] = []
        cursor: str | None = None
        req_id = 1
        while True:
            params: dict = {}
            if cursor:
                params["cursor"] = cursor

            list_resp = await client.post(url, headers=session_headers, json={
                "method": "tools/list",
                "params": params,
                "jsonrpc": "2.0",
                "id": req_id,
            })
            list_resp.raise_for_status()

            data = _parse_mcp_response_body(list_resp)
            result = data.get("result", {}) if data else {}
            all_tools.extend(MCPTool.model_validate(t)
                             for t in result.get("tools", []))

            cursor = result.get("nextCursor")
            req_id += 1
            if not cursor:
                break

        return all_tools


async def _raw_call_mcp_tool(
    connection: dict,
    tool_name: str,
    arguments: dict,
) -> CallToolResult:
    """Call an MCP tool via plain HTTP without a GET SSE stream.

    Same rationale as _raw_list_mcp_tools: avoids the GET-stream deadlock where
    the server returns 202 for tools/call and only delivers the result once the
    GET SSE connection is established (which the server delays until it has
    something to push).

    Upstream:
        https://github.com/modelcontextprotocol/python-sdk/issues/1661
            SDK does not handle 202 Accepted — hangs indefinitely waiting for a
            GET SSE event that never arrives because the stream is not yet open.
        https://github.com/modelcontextprotocol/python-sdk/pull/1674
            Open PR fixing a related race where requests sent immediately after
            initialize are silently dropped before the POST writer is ready.
    """

    url: str = connection["url"]
    extra_headers: dict = connection.get("headers") or {}
    auth: httpx.Auth | None = connection.get("auth")

    request_headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        **extra_headers,
    }

    async with httpx.AsyncClient(
        auth=auth,
        follow_redirects=True,
        # Use a long read timeout for tool calls — some tools may be slow.
        timeout=httpx.Timeout(30.0, read=300.0),
    ) as client:
        # 1. Initialise.
        init_resp = await client.post(url, headers=request_headers, json={
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "auxilia", "version": "1.0"},
            },
            "jsonrpc": "2.0",
            "id": 0,
        })
        init_resp.raise_for_status()

        session_id = init_resp.headers.get("mcp-session-id")
        session_headers = dict(request_headers)
        if session_id:
            session_headers["mcp-session-id"] = session_id

        init_data = _parse_mcp_response_body(init_resp)
        negotiated = (init_data.get("result", {}).get("protocolVersion")
                      if init_data else None)
        if negotiated:
            session_headers["mcp-protocol-version"] = negotiated

        # 2. Notify the server that initialisation is done.
        await client.post(url, headers=session_headers, json={
            "method": "notifications/initialized",
            "jsonrpc": "2.0",
        })

        # 3. Call the tool.
        call_resp = await client.post(url, headers=session_headers, json={
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments,
            },
            "jsonrpc": "2.0",
            "id": 1,
        })
        call_resp.raise_for_status()

        data = _parse_mcp_response_body(call_resp)
        result = data.get("result", {}) if data else {}
        return CallToolResult.model_validate(result)


def _make_raw_lc_tool(
    mcp_tool: MCPTool,
    connection: dict,
    *,
    server_name: str,
    tool_name_prefix: bool,
) -> StructuredTool:
    """Build a LangChain StructuredTool backed by raw HTTP tool calls (no GET stream).

    When session=None, langchain-mcp-adapters creates a fresh ClientSession (and
    therefore a new GET SSE stream) for every tool invocation, reproducing the
    same 202 deadlock on each call. This function constructs a StructuredTool
    whose coroutine uses _raw_call_mcp_tool directly, bypassing that lifecycle.

    Upstream:
        https://github.com/langchain-ai/langchain-mcp-adapters/issues/207
            Per-call session creation — a new MCP handshake runs on every tool
            invocation, adding round-trip overhead and triggering the GET-stream
            deadlock each time.
        https://github.com/langchain-ai/langchain-mcp-adapters/issues/189
            Session persistence across LangGraph turns — same root cause, surfaced
            as state loss between sequential tool calls on stateful servers.
    """
    from langchain_mcp_adapters.tools import _convert_call_tool_result

    lc_name = f"{server_name}_{mcp_tool.name}" if tool_name_prefix and server_name else mcp_tool.name

    raw_meta = getattr(mcp_tool, "meta", None)
    base = mcp_tool.annotations.model_dump() if mcp_tool.annotations is not None else {}
    meta_dict = {"_meta": raw_meta} if raw_meta is not None else {}
    metadata = {**base, **meta_dict} or None

    # Capture loop variables so the closure is stable per tool.
    _tool_name = mcp_tool.name
    _connection = connection

    async def call_tool(**arguments):
        raw_result = await _raw_call_mcp_tool(_connection, _tool_name, arguments)
        return _convert_call_tool_result(raw_result)

    return StructuredTool(
        name=lc_name,
        description=mcp_tool.description or "",
        args_schema=mcp_tool.inputSchema,
        coroutine=call_tool,
        response_format="content_and_artifact",
        metadata=metadata,
    )


_VALID_TOOL_NAME_CHARS = re.compile(r"[^a-zA-Z0-9_-]")
_MAX_TOOL_NAME_LENGTH = 128


def _sanitize_tool_name(name: str) -> str:
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
        base_name = _sanitize_tool_name(original_name)
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


def _build_tool_ui_metadata_map(
    tools: list[Tool],
    mcp_servers: list[MCPServerDB],
) -> dict[str, dict[str, str]]:
    server_id_by_name = {server.name: str(server.id) for server in mcp_servers}
    server_names = list(server_id_by_name.keys())
    metadata_by_tool_name: dict[str, dict[str, str]] = {}

    for tool in tools:
        tool_name = getattr(tool, "name", None)
        if not isinstance(tool_name, str) or not tool_name:
            continue

        resource_uri = _extract_mcp_app_resource_uri(tool)
        if not resource_uri:
            continue

        server_name = _resolve_server_name_from_prefixed_tool_name(
            tool_name, server_names)
        if not server_name:
            continue

        server_id = server_id_by_name.get(server_name)
        if not server_id:
            continue

        metadata_by_tool_name[tool_name] = {
            "mcp_app_resource_uri": resource_uri,
            "mcp_server_id": server_id,
        }

    return metadata_by_tool_name


class ModelProvider(BaseModel):
    name: str
    api_key: str


class Model(BaseModel):
    name: str
    provider: str


LLM_PROVIDERS = []
MODELS = []

if model_provider_settings.openai_api_key:
    LLM_PROVIDERS.append(ModelProvider(
        name="openai", api_key=model_provider_settings.openai_api_key))
    MODELS.append(Model(name="gpt-4o-mini", provider="openai"))

if model_provider_settings.deepseek_api_key:
    LLM_PROVIDERS.append(ModelProvider(
        name="deepseek", api_key=model_provider_settings.deepseek_api_key))
    MODELS.append(Model(name="deepseek-chat", provider="deepseek"))
    MODELS.append(Model(name="deepseek-reasoner", provider="deepseek"))

if model_provider_settings.anthropic_api_key:
    LLM_PROVIDERS.append(ModelProvider(
        name="anthropic", api_key=model_provider_settings.anthropic_api_key))
    MODELS.append(Model(name="claude-haiku-4-5", provider="anthropic"))
    MODELS.append(Model(name="claude-sonnet-4-5", provider="anthropic"))
    MODELS.append(Model(name="claude-opus-4-5", provider="anthropic"))

if model_provider_settings.google_api_key:
    LLM_PROVIDERS.append(ModelProvider(
        name="google", api_key=model_provider_settings.google_api_key))
    MODELS.append(Model(name="gemini-3-flash-preview", provider="google"))
    MODELS.append(Model(name="gemini-3-pro-preview", provider="google"))


class ChatModelFactory:

    def create(self, provider: str, model_id: str, api_key: str):

        match provider:
            case "openai":
                return ChatOpenAI(model=model_id, api_key=api_key)
            case "deepseek":
                return ChatDeepSeek(model=model_id, api_key=api_key)
            case "anthropic":
                return ChatAnthropic(
                    model=model_id,
                    temperature=1,
                    max_tokens=2048,
                    streaming=True,
                    timeout=None,
                    thinking={"type": "enabled", "budget_tokens": 1024},
                    max_retries=2,
                    api_key=api_key
                )
            case "google":
                return ChatGoogleGenerativeAI(
                    model=model_id,
                    temperature=0,
                    max_tokens=None,
                    timeout=None,
                    max_retries=2,
                    streaming=True,
                    include_thoughts=True,
                    thinking_budget=-1,
                    api_key=api_key,
                )
            case _:
                raise ValueError(f"Provider {provider} not supported")


@dataclass
class AgentRuntimeDependencies:
    model_factory: ChatModelFactory
    mcp_client_config_factory: MCPClientConfigFactory


def build_agent_deps(thread: ThreadDB, db: AsyncSession) -> AgentRuntimeDependencies:
    """Create the standard agent runtime dependencies."""

    return AgentRuntimeDependencies(
        model_factory=ChatModelFactory(),
        mcp_client_config_factory=MCPClientConfigFactory(
            resolve_api_key=lambda mcp_server_config: get_mcp_server_api_key(
                mcp_server_config.id, db),
            resolve_storage=lambda mcp_server_config: TokenStorageFactory(
            ).get_storage(thread.user_id, mcp_server_config.id),
        ),
    )


class AgentRuntime:
    def __init__(self, thread: ThreadDB, db: AsyncSession, deps: AgentRuntimeDependencies, timer: RequestTimer | None = None):
        self.thread = thread
        self.tools = None
        self.tool_ui_metadata: dict[str, dict[str, str]] = {}
        self.db = db
        self._deps = deps
        self._timer = timer or RequestTimer("invoke", enabled=False)
        self.callbacks = [
            langfuse_callback_handler] if langfuse_callback_handler is not None else []

    @property
    def metadata(self) -> dict:
        return {
            "user_id": self.thread.user_id,
            "thread_id": self.thread.id,
            "agent_id": self.thread.agent_id,
        }

    @property
    def stream_config(self) -> dict:
        return {
            "configurable": {"thread_id": self.thread.id},
            "recursion_limit": agent_settings.recursion_limit,
            "callbacks": self.callbacks,
            "metadata": self.metadata
        }

    async def build_multi_mcp_server_configs(self, mcp_server_configs: list[dict]) -> dict:

        return {
            mcp_server_config.name: await self._deps.mcp_client_config_factory.build(mcp_server_config)
            for mcp_server_config in mcp_server_configs
        }

    async def get_tools(
        self,
        multi_mcp_server_configs: dict,
        tool_settings_map: dict[str, dict[str, str] | None],
    ) -> list[Tool]:
        """
        Fetch tools from MCP servers and filter based on tool settings per server.

        Args:
            multi_mcp_server_configs: Dict mapping server_id to server config
            tool_settings_map: Dict mapping server_name to tool status dict (e.g. {"tool_name": "always_allow"})

        Returns:
            Filtered list of tools
        """
        async def fetch_and_filter_tools(server_id: str):
            connection = multi_mcp_server_configs[server_id]

            # Use raw HTTP to avoid the ~15 s GET-stream race (see _raw_list_mcp_tools).
            async with self._timer.aspan(f"mcp_list_tools:{server_id}"):
                raw_mcp_tools = await _raw_list_mcp_tools(connection)

            # Build LangChain tools backed by raw HTTP tool calls (same fix for
            # tool invocations — avoids the same GET-stream deadlock).
            lc_tools = [
                _make_raw_lc_tool(
                    mcp_tool=tool,
                    connection=connection,
                    server_name=server_id,
                    tool_name_prefix=True,
                )
                for tool in raw_mcp_tools
            ]

            tool_settings = tool_settings_map.get(str(server_id))
            always_allowed_tools = [tool for tool in lc_tools if tool.name in [
                server_id + "_" + tool for tool, status in tool_settings.items() if status == "always_allow"]]
            need_approval_tools = [tool for tool in lc_tools if tool.name in [
                server_id + "_" + tool for tool, status in tool_settings.items() if status == "needs_approval"]]
            return always_allowed_tools, need_approval_tools

        tasks = [
            fetch_and_filter_tools(server_id)
            for server_id in multi_mcp_server_configs.keys()
        ]
        results = await asyncio.gather(*tasks)

        always_allowed_tools = [
            tool for result in results for tool in result[0]]
        need_approval_tools = [
            tool for result in results for tool in result[1]]

        return always_allowed_tools, need_approval_tools

    async def get_model_provider(self, model_name: str = "gpt-4o-mini") -> ModelProvider:
        model = next(model for model in MODELS if model.name == model_name)
        return next(
            provider for provider in LLM_PROVIDERS if model.provider == provider.name
        )

    @classmethod
    async def create(cls, thread: ThreadDB, db: AsyncSession, deps: AgentRuntimeDependencies, timer: RequestTimer | None = None):
        self = cls(thread, db, deps, timer=timer)
        await self.initialize()
        return self

    async def initialize(self):
        async with self._timer.aspan("read_agent"):
            self.config = await AgentService(self.db).get_agent(self.thread.agent_id)

        async with self._timer.aspan("fetch_mcp_servers"):
            result = await self.db.execute(
                select(MCPServerDB).where(
                    MCPServerDB.id.in_(
                        [mcp_server.id for mcp_server in self.config.mcp_servers]
                    )
                )
            )
            mcp_servers = result.scalars().all()
            mcp_servers = list(mcp_servers)

        async with self._timer.aspan("build_mcp_configs"):
            mcp_server_configs = await self.build_multi_mcp_server_configs(mcp_servers)

        tool_settings = {
            next(server.name for server in mcp_servers if server.id == mcp_server.id): mcp_server.tools
            for mcp_server in self.config.mcp_servers
        }

        async with self._timer.aspan("get_tools"):
            self.tools = await self.get_tools(mcp_server_configs, tool_settings)

        with self._timer.span("build_tool_metadata"):
            all_tools = self.tools[0] + self.tools[1]
            raw_tool_ui_metadata = _build_tool_ui_metadata_map(
                all_tools, mcp_servers)
            name_map = _sanitize_tools_in_place(all_tools)
            self.tool_ui_metadata = {
                name_map.get(tool_name, tool_name): metadata
                for tool_name, metadata in raw_tool_ui_metadata.items()
            }

    async def stream(
        self,
        messages: list[Message],
        message_id: str | None = None,
        stream_adapter: str = "ai_sdk",
        commands: list[str] | None = None,
    ):
        """Wrapper to keep checkpointer alive during streaming.

        Args:
            messages: List of messages to process
            message_id: Optional message ID from frontend (used when resuming after HITL approval)
            stream_adapter: Which stream adapter to use ("ai_sdk" or "slack")
            commands: Optional list of explicit commands ("approve"/"reject") for direct resume
                      (bypasses message-based command extraction)
        """
        try:
            _checkpointer_t0 = time.perf_counter()
            async with AsyncPostgresSaver.from_conn_string(get_psycopg_conn_string()) as checkpointer:
                self._timer.record("checkpointer_setup",
                                   time.perf_counter() - _checkpointer_t0)

                async with self._timer.aspan("model_and_agent_build"):
                    model_provider = await self.get_model_provider(self.thread.model_id)
                    chat_model = self._deps.model_factory.create(
                        model_provider.name, self.thread.model_id, model_provider.api_key)

                    tools = self.tools[0] + self.tools[1]
                    need_approval_tools = self.tools[1]

                    # Wrap each tool's coroutine so that anyio ExceptionGroups (e.g. from
                    # HTTP errors in MCP streamable-HTTP sessions) are converted to
                    # ToolException before they reach LangGraph's ToolNode.  The default
                    # ToolNode error handler only handles ToolInvocationError and re-raises
                    # everything else, which would crash the whole stream.  By raising
                    # ToolException instead, BaseTool.arun catches it and returns the error
                    # as a tool result string, keeping the stream alive and letting the LLM
                    # report the error to the user.
                    for tool in tools:
                        wrap_mcp_tool_errors(tool)
                        if tool.name in self.tool_ui_metadata:
                            inject_ui_metadata_into_tool(
                                tool, self.tool_ui_metadata[tool.name])

                    system_prompt = {
                        "type": "text",
                        "text": self.config.instructions or "",
                    }

                    if model_provider == "anthropic":
                        system_prompt["cache_control"] = {"type": "ephemeral"}

                    agent = create_agent(
                        model=chat_model,
                        tools=tools,
                        system_prompt=SystemMessage(content=[system_prompt]),
                        checkpointer=checkpointer,
                        middleware=[
                            HumanInTheLoopMiddleware(
                                interrupt_on={
                                    tool.name: True for tool in need_approval_tools
                                },
                                description_prefix="Tool execution pending approval",
                            )
                        ],
                    )

                with self._timer.span("message_processing"):
                    # Use explicit commands if provided, otherwise extract from messages
                    if commands is not None:
                        extracted_commands = commands
                        rejected_tool_calls = []
                        approved_tool_call_ids = []
                    else:
                        langchain_messages = [to_langchain_message(
                            message) for message in messages]
                        extracted_commands = sum([extract_commands(message)
                                                  for message in messages if extract_commands(message)], [])

                        # Extract rejected tool calls to emit error events in the stream
                        rejected_tool_calls = sum(
                            [extract_rejected_tool_calls(message)
                             for message in messages],
                            []
                        )

                        # Extract approved tool call IDs to skip their input events (already shown in UI)
                        approved_tool_call_ids = sum(
                            [extract_approved_tool_call_ids(message)
                             for message in messages],
                            []
                        )

                is_resume = len(extracted_commands) > 0
                resume_message_id = message_id if is_resume else None

                stream_input = Command(
                    resume={"decisions": [{"type": command} for command in extracted_commands]}) if is_resume else {"messages": langchain_messages}

                langchain_stream = agent.astream_events(
                    stream_input,
                    version="v2",
                    config=self.stream_config
                )

                if stream_adapter == "ai_sdk":
                    ai_sdk_stream_adapter = AISDKStreamAdapter(
                        message_id=resume_message_id,
                        is_resume=is_resume,
                        rejected_tool_calls=rejected_tool_calls,
                        approved_tool_call_ids=approved_tool_call_ids,
                        tool_ui_metadata=self.tool_ui_metadata,
                    )
                    stream = ai_sdk_stream_adapter.stream(
                        langchain_stream)
                elif stream_adapter == "slack":
                    slack_stream_adapter = SlackStreamAdapter()
                    stream = slack_stream_adapter.stream(
                        langchain_stream)

                _first_chunk = True
                _stream_t0 = time.perf_counter()
                async for chunk in stream:
                    if _first_chunk:
                        self._timer.record(
                            "time_to_first_chunk", time.perf_counter() - _stream_t0)
                        _first_chunk = False
                    yield chunk
                self._timer.record(
                    "stream_total", time.perf_counter() - _stream_t0)
        finally:
            self._timer.summary()
