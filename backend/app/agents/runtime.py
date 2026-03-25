import asyncio
import logging
import re
import time
from dataclasses import dataclass

from deepagents.backends import StateBackend
from deepagents.middleware.subagents import CompiledSubAgent, SubAgentMiddleware
from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware
from langchain_ai_sdk_adapter import to_lc_messages
from langchain_anthropic.middleware import AnthropicPromptCachingMiddleware
from langchain_core.messages import (
    AIMessage as LCAIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage as LCToolMessage,
)
from langchain_core.tools import Tool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.agents.core.service import AgentService
from app.agents.hitl import (
    extract_approved_tool_call_ids,
    extract_commands,
    extract_rejected_tool_calls,
)
from app.agents.settings import agent_settings
from app.agents.stream import (
    AISDKStreamAdapter,
    LangGraphStreamAdapter,
    SlackStreamAdapter,
)
from app.database import get_psycopg_conn_string
from app.integrations.langfuse.callback import langfuse_callback_handler
from app.mcp.client.factory import MCPClientConfigFactory
from app.mcp.client.storage import TokenStorageFactory
from app.mcp.client.tools import inject_ui_metadata_into_tool, wrap_mcp_tool_errors
from app.mcp.servers.models import MCPServerDB
from app.mcp.servers.repository import get_mcp_server_api_key
from app.model_providers.catalog import (
    LLM_PROVIDERS,
    MODELS,
    ChatModelFactory,
    ModelProvider,
)
from app.models.message import Message
from app.threads.models import ThreadDB
from app.utils.timer import RequestTimer


logger = logging.getLogger(__name__)


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
            tool_name, server_names
        )
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


async def get_regeneration_checkpoint_id(agent, config: dict) -> str | None:
    """Walk back checkpoint history to find the state before the last user message was added."""
    current_state = await agent.aget_state(config)
    current_messages = current_state.values.get("messages", [])
    current_human_count = sum(1 for m in current_messages if m.type == "human")

    async for state in agent.aget_state_history(config):
        messages = state.values.get("messages", [])
        human_count = sum(1 for m in messages if m.type == "human")
        if human_count < current_human_count:
            return state.config["configurable"]["checkpoint_id"]

    return None


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
                mcp_server_config.id, db
            ),
            resolve_storage=lambda mcp_server_config: TokenStorageFactory().get_storage(
                thread.user_id, mcp_server_config.id
            ),
        ),
    )


class AgentRuntime:
    def __init__(
        self,
        thread: ThreadDB,
        db: AsyncSession,
        deps: AgentRuntimeDependencies,
        timer: RequestTimer | None = None,
    ):
        self.thread = thread
        self.tools = None
        self.tool_ui_metadata: dict[str, dict[str, str]] = {}
        self.subagent_configs: list[dict] = []
        self.db = db
        self._deps = deps
        self._timer = timer or RequestTimer("invoke", enabled=False)
        self.callbacks = (
            [langfuse_callback_handler] if langfuse_callback_handler is not None else []
        )

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
            "metadata": self.metadata,
        }

    async def _resolve_stream_config(self, agent, trigger: str | None) -> dict:
        """Build the stream config, forking from an earlier checkpoint on regenerate."""
        config = self.stream_config
        if trigger == "regenerate-message":
            checkpoint_id = await get_regeneration_checkpoint_id(agent, config)
            if checkpoint_id:
                config["configurable"]["checkpoint_id"] = checkpoint_id
        return config

    async def build_multi_mcp_server_configs(
        self, mcp_server_configs: list[dict]
    ) -> dict:

        return {
            mcp_server_config.name: await self._deps.mcp_client_config_factory.build(
                mcp_server_config
            )
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
        client = MultiServerMCPClient(multi_mcp_server_configs, tool_name_prefix=True)

        async def fetch_and_filter_tools(server_id: str):
            async with self._timer.aspan(f"mcp_list_tools:{server_id}"):
                lc_tools = await client.get_tools(server_name=server_id)

            tool_settings = tool_settings_map.get(str(server_id))
            always_allowed_tools = [
                tool
                for tool in lc_tools
                if tool.name
                in [
                    server_id + "_" + tool
                    for tool, status in tool_settings.items()
                    if status == "always_allow"
                ]
            ]
            need_approval_tools = [
                tool
                for tool in lc_tools
                if tool.name
                in [
                    server_id + "_" + tool
                    for tool, status in tool_settings.items()
                    if status == "needs_approval"
                ]
            ]
            return always_allowed_tools, need_approval_tools

        tasks = [
            fetch_and_filter_tools(server_id)
            for server_id in multi_mcp_server_configs.keys()
        ]
        results = await asyncio.gather(*tasks)

        always_allowed_tools = [tool for result in results for tool in result[0]]
        need_approval_tools = [tool for result in results for tool in result[1]]

        return always_allowed_tools, need_approval_tools

    async def get_model_provider(
        self, model_name: str = "gpt-4o-mini"
    ) -> ModelProvider:
        model = next(model for model in MODELS if model.name == model_name)
        return next(
            provider for provider in LLM_PROVIDERS if model.provider == provider.name
        )

    @classmethod
    async def create(
        cls,
        thread: ThreadDB,
        db: AsyncSession,
        deps: AgentRuntimeDependencies,
        timer: RequestTimer | None = None,
    ):
        self = cls(thread, db, deps, timer=timer)
        await self.initialize()
        return self

    async def initialize(self):
        async with self._timer.aspan("read_agent"):
            self.config = await AgentService(self.db).get_agent(
                self.thread.agent_id, include_archived=True
            )

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
            next(
                server.name for server in mcp_servers if server.id == mcp_server.id
            ): mcp_server.tools
            for mcp_server in self.config.mcp_servers
        }

        async with self._timer.aspan("get_tools"):
            self.tools = await self.get_tools(mcp_server_configs, tool_settings)

        with self._timer.span("build_tool_metadata"):
            all_tools = self.tools[0] + self.tools[1]
            raw_tool_ui_metadata = _build_tool_ui_metadata_map(all_tools, mcp_servers)
            name_map = _sanitize_tools_in_place(all_tools)
            self.tool_ui_metadata = {
                name_map.get(tool_name, tool_name): metadata
                for tool_name, metadata in raw_tool_ui_metadata.items()
            }

        # Load subagent configs + tools if this agent has subagents
        if self.config.subagents:
            async with self._timer.aspan("load_subagents"):
                self.subagent_configs = await self._load_subagent_configs()

    async def _load_subagent_configs(self) -> list[dict]:
        """Load each subagent's config metadata (no tools yet — those are loaded at stream time)."""
        configs = []
        for sub in self.config.subagents:
            sub_config = await AgentService(self.db).get_agent(
                sub.id, include_archived=True
            )

            # Resolve MCP server objects for later tool loading
            sub_mcp_server_ids = [s.id for s in sub_config.mcp_servers]
            sub_mcp_servers = []
            if sub_mcp_server_ids:
                result = await self.db.execute(
                    select(MCPServerDB).where(MCPServerDB.id.in_(sub_mcp_server_ids))
                )
                sub_mcp_servers = list(result.scalars().all())

            configs.append(
                {
                    "name": sub_config.name,
                    "description": sub_config.description or sub_config.name,
                    "instructions": sub_config.instructions or "",
                    "mcp_servers": sub_mcp_servers,
                    "mcp_server_bindings": sub_config.mcp_servers,
                }
            )
        return configs

    async def _load_subagent_tools(self, sub_cfg: dict) -> list[Tool]:
        """Fetch MCP tools for a subagent. Must be called within the streaming context."""
        mcp_servers = sub_cfg["mcp_servers"]
        if not mcp_servers:
            return []

        mcp_configs = await self.build_multi_mcp_server_configs(mcp_servers)
        tool_settings = {
            next(s.name for s in mcp_servers if s.id == ms.id): ms.tools
            for ms in sub_cfg["mcp_server_bindings"]
        }
        always_allowed, need_approval = await self.get_tools(mcp_configs, tool_settings)
        sub_tools = always_allowed + need_approval
        _sanitize_tools_in_place(sub_tools)
        for tool in sub_tools:
            wrap_mcp_tool_errors(tool)
        return sub_tools

    async def stream(
        self,
        messages: list[Message],
        message_id: str | None = None,
        stream_adapter: str = "ai_sdk",
        commands: list[str] | None = None,
        trigger: str | None = None,
    ):
        """Wrapper to keep checkpointer alive during streaming.

        Args:
            messages: List of messages to process
            message_id: Optional message ID from frontend (used when resuming after HITL approval)
            stream_adapter: Which stream adapter to use ("ai_sdk" or "slack")
            commands: Optional list of explicit commands ("approve"/"reject") for direct resume
                      (bypasses message-based command extraction)
            trigger: Optional trigger from AI SDK ("submit-message", "regenerate-message")
        """
        try:
            _checkpointer_t0 = time.perf_counter()
            async with AsyncPostgresSaver.from_conn_string(
                get_psycopg_conn_string()
            ) as checkpointer:
                self._timer.record(
                    "checkpointer_setup", time.perf_counter() - _checkpointer_t0
                )

                async with self._timer.aspan("model_and_agent_build"):
                    model_provider = await self.get_model_provider(self.thread.model_id)
                    chat_model = self._deps.model_factory.create(
                        model_provider.name,
                        self.thread.model_id,
                        model_provider.api_key,
                    )

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
                                tool, self.tool_ui_metadata[tool.name]
                            )

                    system_prompt = {
                        "type": "text",
                        "text": self.config.instructions or "",
                    }

                    middlewares = [
                        HumanInTheLoopMiddleware(
                            interrupt_on={
                                tool.name: True for tool in need_approval_tools
                            },
                            description_prefix="Tool execution pending approval",
                        )
                    ]

                    if model_provider.name == "anthropic":
                        middlewares.append(AnthropicPromptCachingMiddleware(ttl="5m"))
                        # system_prompt["cache_control"] = {"type": "ephemeral"}

                    agent = create_agent(
                        model=chat_model,
                        tools=tools,
                        system_prompt=SystemMessage(content=[system_prompt]),
                        checkpointer=checkpointer,
                        middleware=middlewares,
                    )

                with self._timer.span("message_processing"):
                    # Use explicit commands if provided, otherwise extract from messages
                    approved_tool_calls_meta: list[dict] = []
                    if commands is not None:
                        extracted_commands = commands
                        rejected_tool_calls = []
                        approved_tool_call_ids = []
                    else:
                        langchain_messages = await to_lc_messages(
                            [m.model_dump() for m in messages]
                        )
                        extracted_commands = sum(
                            [
                                extract_commands(message)
                                for message in messages
                                if extract_commands(message)
                            ],
                            [],
                        )

                        # Extract rejected tool calls to emit error events in the stream
                        rejected_tool_calls = sum(
                            [
                                extract_rejected_tool_calls(message)
                                for message in messages
                            ],
                            [],
                        )

                        # Extract approved tool call IDs to skip their input events (already shown in UI)
                        approved_tool_call_ids = sum(
                            [
                                extract_approved_tool_call_ids(message)
                                for message in messages
                            ],
                            [],
                        )

                is_resume = len(extracted_commands) > 0
                resume_message_id = message_id if is_resume else None

                # On resume, read pending tool calls from the LangGraph checkpoint.
                # This is more reliable than parsing frontend messages because:
                #   1. The checkpoint stores the exact LLM-generated tool_call_ids
                #   2. Frontend JSON bodies go through Axios camelCase→snake_case
                #      conversion which can break Pydantic field name matching
                if is_resume:
                    checkpoint_data = await checkpointer.aget(config=self.stream_config)
                    if checkpoint_data:
                        msgs = checkpoint_data["channel_values"].get("messages", [])
                        for msg in reversed(msgs):
                            tool_calls = getattr(msg, "tool_calls", None)
                            if tool_calls:
                                approved_tool_calls_meta = [
                                    {
                                        "toolCallId": tc.get("id")
                                        if isinstance(tc, dict)
                                        else getattr(tc, "id", None),
                                        "toolName": tc.get("name")
                                        if isinstance(tc, dict)
                                        else getattr(tc, "name", None),
                                        "input": tc.get("args", {})
                                        if isinstance(tc, dict)
                                        else getattr(tc, "args", {}),
                                    }
                                    for tc in tool_calls
                                ]
                                approved_tool_calls_meta = [
                                    tc
                                    for tc in approved_tool_calls_meta
                                    if tc["toolCallId"] and tc["toolName"]
                                ]
                                break

                stream_input = (
                    Command(
                        resume={
                            "decisions": [
                                {"type": command} for command in extracted_commands
                            ]
                        }
                    )
                    if is_resume
                    else {"messages": langchain_messages}
                )

                config = await self._resolve_stream_config(agent, trigger)
                langchain_stream = agent.astream(
                    stream_input,
                    config=config,
                    stream_mode=["messages", "values"],
                )

                if stream_adapter == "ai_sdk":
                    ai_sdk_stream_adapter = AISDKStreamAdapter(
                        message_id=resume_message_id,
                        is_resume=is_resume,
                        rejected_tool_calls=rejected_tool_calls,
                        approved_tool_call_ids=approved_tool_call_ids,
                        approved_tool_calls=approved_tool_calls_meta,
                        tool_ui_metadata=self.tool_ui_metadata,
                    )
                    stream = ai_sdk_stream_adapter.stream(langchain_stream)
                elif stream_adapter == "slack":
                    slack_stream_adapter = SlackStreamAdapter()
                    stream = slack_stream_adapter.stream(langchain_stream)

                _first_chunk = True
                _stream_t0 = time.perf_counter()
                async for chunk in stream:
                    if _first_chunk:
                        self._timer.record(
                            "time_to_first_chunk", time.perf_counter() - _stream_t0
                        )
                        _first_chunk = False
                    yield chunk
                self._timer.record("stream_total", time.perf_counter() - _stream_t0)
        finally:
            self._timer.summary()

    async def stream_langgraph(
        self,
        input: dict | None = None,
        command: dict | None = None,
        trigger: str | None = None,
        config_overrides: dict | None = None,
    ):
        """Stream using the native LangGraph SSE protocol.

        Subgraph events are always streamed so the frontend SDK can track
        subagent lifecycle (status, messages, results) when present.

        Args:
            input: Graph input dict (e.g. {"messages": [{"type": "human", ...}]}) or None for resume.
            command: LangGraph Command dict (e.g. {"resume": {...}}) for HITL resume.
            trigger: Optional trigger ("regenerate-message") for regeneration.
            config_overrides: Optional config dict with configurable overrides (e.g. checkpoint_id).
        """
        try:
            _checkpointer_t0 = time.perf_counter()
            async with AsyncPostgresSaver.from_conn_string(
                get_psycopg_conn_string()
            ) as checkpointer:
                self._timer.record(
                    "checkpointer_setup", time.perf_counter() - _checkpointer_t0
                )

                async with self._timer.aspan("model_and_agent_build"):
                    model_provider = await self.get_model_provider(self.thread.model_id)
                    chat_model = self._deps.model_factory.create(
                        model_provider.name,
                        self.thread.model_id,
                        model_provider.api_key,
                    )

                    tools = self.tools[0] + self.tools[1]
                    need_approval_tools = self.tools[1]

                    for tool in tools:
                        wrap_mcp_tool_errors(tool)
                        if tool.name in self.tool_ui_metadata:
                            inject_ui_metadata_into_tool(
                                tool, self.tool_ui_metadata[tool.name]
                            )

                    system_prompt = {
                        "type": "text",
                        "text": self.config.instructions or "",
                    }

                    middlewares = [
                        HumanInTheLoopMiddleware(
                            interrupt_on={
                                tool.name: True for tool in need_approval_tools
                            },
                            description_prefix="Tool execution pending approval",
                        )
                    ]

                    # if model_provider.name == "anthropic":
                    #     middlewares.append(
                    #         AnthropicPromptCachingMiddleware(ttl="5m"))

                    # Build SubAgentMiddleware when subagents are configured
                    if self.subagent_configs:
                        compiled_subagents = []
                        for sub_cfg in self.subagent_configs:
                            sub_tools = await self._load_subagent_tools(sub_cfg)
                            sub_system_prompt = SystemMessage(
                                content=[
                                    {"type": "text", "text": sub_cfg["instructions"]}
                                ]
                            )
                            sub_agent = create_agent(
                                model=chat_model,
                                tools=sub_tools,
                                system_prompt=sub_system_prompt,
                            )
                            # Sanitize name to a valid identifier for the LLM
                            slug = _sanitize_tool_name(sub_cfg["name"])
                            compiled_subagents.append(
                                CompiledSubAgent(
                                    name=slug,
                                    description=f'{sub_cfg["name"]}: {sub_cfg["description"]}',
                                    runnable=sub_agent,
                                )
                            )
                        middlewares.append(
                            SubAgentMiddleware(
                                backend=StateBackend,
                                subagents=compiled_subagents,
                            )
                        )

                    agent = create_agent(
                        model=chat_model,
                        tools=tools,
                        system_prompt=SystemMessage(content=[system_prompt]),
                        checkpointer=checkpointer,
                        middleware=middlewares,
                    )

                # Determine stream input
                if command is not None:
                    stream_input = Command(resume=command.get("resume"))
                else:
                    lc_messages = _dicts_to_lc_messages(
                        input.get("messages", []) if input else []
                    )
                    stream_input = {"messages": lc_messages}

                # Build config
                config = self.stream_config
                if config_overrides and config_overrides.get("configurable"):
                    # Allow frontend to pass checkpoint_id for regeneration
                    config["configurable"].update(config_overrides["configurable"])

                if trigger == "regenerate-message":
                    checkpoint_id = await get_regeneration_checkpoint_id(agent, config)
                    if checkpoint_id:
                        config["configurable"]["checkpoint_id"] = checkpoint_id

                langchain_stream = agent.astream(
                    stream_input,
                    config=config,
                    stream_mode=["messages", "values", "updates"],
                    subgraphs=True,
                )

                adapter = LangGraphStreamAdapter(subgraphs=True)
                _first_chunk = True
                _stream_t0 = time.perf_counter()
                async for chunk in adapter.stream(langchain_stream):
                    if _first_chunk:
                        self._timer.record(
                            "time_to_first_chunk", time.perf_counter() - _stream_t0
                        )
                        _first_chunk = False
                    yield chunk
                self._timer.record("stream_total", time.perf_counter() - _stream_t0)
        finally:
            self._timer.summary()


def _dicts_to_lc_messages(dicts: list[dict]) -> list[BaseMessage]:
    """Convert message dicts (LangChain format) to LangChain BaseMessage objects."""
    messages: list[BaseMessage] = []
    for d in dicts:
        msg_type = d.get("type", d.get("role", "human"))
        content = d.get("content", "")
        msg_id = d.get("id")

        if msg_type in ("human", "user"):
            messages.append(HumanMessage(content=content, id=msg_id))
        elif msg_type in ("ai", "assistant"):
            kwargs: dict = {"content": content, "id": msg_id}
            if d.get("tool_calls"):
                kwargs["tool_calls"] = d["tool_calls"]
            messages.append(LCAIMessage(**kwargs))
        elif msg_type == "tool":
            messages.append(
                LCToolMessage(
                    content=content,
                    tool_call_id=d.get("tool_call_id", ""),
                    id=msg_id,
                )
            )
        elif msg_type == "system":
            messages.append(SystemMessage(content=content, id=msg_id))
        else:
            messages.append(HumanMessage(content=content, id=msg_id))
    return messages
