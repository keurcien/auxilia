import logging
from dataclasses import dataclass

from deepagents import create_deep_agent
from deepagents.backends import StateBackend
from deepagents.middleware.subagents import CompiledSubAgent, SubAgentMiddleware
from langchain.agents.middleware import ToolCallLimitMiddleware

from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.core.service import AgentService
from app.agents.models import AgentRead
from app.agents.settings import agent_settings
from app.agents.stream import LangGraphStreamAdapter, SlackStreamAdapter
from app.agents.tool_errors import ToolErrorMiddleware
from app.agents.toolset import Toolset, sanitize_tool_name
from app.database import get_psycopg_conn_string
from app.integrations.langfuse.callback import langfuse_callback_handler
from app.model_providers.catalog import LLM_PROVIDERS, MODELS, ChatModelFactory
from app.sandbox.settings import sandbox_settings
from app.threads.models import ThreadDB


logger = logging.getLogger(__name__)


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
class Agent:
    """An agent config with its resolved toolset. Used for both parent and subagents."""

    config: AgentRead
    toolset: Toolset

    @classmethod
    async def resolve(
        cls,
        agent_id,
        db: AsyncSession,
        user_id: str,
        *,
        is_parent: bool = False,
    ) -> "Agent":
        config = await AgentService(db).get_agent(agent_id, include_archived=True)
        toolset = await Toolset.resolve(config.mcp_servers, db, user_id)
        if is_parent:
            toolset.apply_ui_metadata()
        return cls(config=config, toolset=toolset)

    def compile(self, model) -> CompiledSubAgent:
        """Compile into a CompiledSubAgent runnable (for subagent use)."""
        return CompiledSubAgent(
            name=sanitize_tool_name(self.config.name),
            description=f"{self.config.name}: {self.config.description or self.config.name}",
            runnable=create_agent(
                model=model,
                tools=self.toolset.all,
                system_prompt=SystemMessage(
                    content=[
                        {"type": "text", "text": self.config.instructions or ""}
                    ]
                ),
            ),
        )


class AgentRuntime:
    def __init__(
        self,
        thread: ThreadDB,
        agent: Agent,
        model,
        middleware: list,
        callbacks: list,
    ):
        self.thread = thread
        self.agent = agent
        self.model = model
        self.middleware = middleware
        self.callbacks = callbacks

    @property
    def metadata(self) -> dict:
        return {
            "user_id": self.thread.user_id,
            "thread_id": self.thread.id,
            "agent_id": self.thread.agent_id,
        }

    @property
    def _stream_config(self) -> dict:
        return {
            "configurable": {"thread_id": self.thread.id},
            "recursion_limit": agent_settings.recursion_limit,
            "callbacks": self.callbacks,
            "metadata": self.metadata,
        }

    @classmethod
    async def build(
        cls,
        thread: ThreadDB,
        db: AsyncSession,
    ) -> "AgentRuntime":
        user_id = str(thread.user_id)

        agent = await Agent.resolve(thread.agent_id, db, user_id, is_parent=True)

        model_entry = next(m for m in MODELS if m.name == thread.model_id)
        provider = next(p for p in LLM_PROVIDERS if p.name ==
                        model_entry.provider)
        model = ChatModelFactory().create(
            provider.name, thread.model_id, provider.api_key
        )

        # Build middleware stack
        middleware = [
            ToolCallLimitMiddleware(run_limit=(
                agent_settings.recursion_limit - 1) // 2, exit_behavior="end"),
            HumanInTheLoopMiddleware(
                interrupt_on=agent.toolset.interrupt_on,
                description_prefix="Tool execution pending approval",
            )
        ]

        subagents = []
        if agent.config.subagents:
            for sub in agent.config.subagents:
                subagents.append(await Agent.resolve(sub.id, db, user_id))

        if subagents:
            compiled = [s.compile(model) for s in subagents]
            middleware.append(
                SubAgentMiddleware(backend=StateBackend, subagents=compiled)
            )

        callbacks = (
            [langfuse_callback_handler] if langfuse_callback_handler is not None else []
        )

        return cls(
            thread=thread,
            agent=agent,
            model=model,
            middleware=middleware,
            callbacks=callbacks,
        )

    def _build_agent(self, checkpointer):
        """Build the LangGraph agent (deep or standard) with the given checkpointer."""
        if self.agent.config.sandbox and sandbox_settings.enabled:
            return self._build_deep_agent(checkpointer)
        return create_agent(
            model=self.model,
            tools=self.agent.toolset.all,
            system_prompt=SystemMessage(self.agent.config.instructions),
            checkpointer=checkpointer,
            middleware=self.middleware,
        )

    def _resolve_input(self, input: dict | None, command: dict | None):
        """Resolve raw input/command dicts into the value to pass to the agent."""
        if command is not None:
            return Command(resume=command.get("resume"))
        lc_messages = _dicts_to_lc_messages(
            input.get("messages", []) if input else []
        )
        return {"messages": lc_messages}

    async def _resolve_config(
        self,
        agent,
        trigger: str | None,
        config_overrides: dict | None,
    ) -> dict:
        """Build the run config, applying overrides and regeneration logic."""
        config = self._stream_config
        if config_overrides and config_overrides.get("configurable"):
            config["configurable"].update(config_overrides["configurable"])
        if trigger == "regenerate-message":
            checkpoint_id = await get_regeneration_checkpoint_id(agent, config)
            if checkpoint_id:
                config["configurable"]["checkpoint_id"] = checkpoint_id
        return config

    async def stream(
        self,
        input: dict | None = None,
        command: dict | None = None,
        trigger: str | None = None,
        config_overrides: dict | None = None,
        stream_adapter: str = "langgraph",
    ):
        """Stream using the native LangGraph SSE protocol.

        Args:
            input: Graph input dict (e.g. {"messages": [{"type": "human", ...}]}) or None for resume.
            command: LangGraph Command dict (e.g. {"resume": {...}}) for HITL resume.
            trigger: Optional trigger ("regenerate-message") for regeneration.
            config_overrides: Optional config dict with configurable overrides.
            stream_adapter: Which stream adapter to use ("langgraph" or "slack").
        """
        async with AsyncPostgresSaver.from_conn_string(
            get_psycopg_conn_string()
        ) as checkpointer:
            agent = self._build_agent(checkpointer)
            stream_input = self._resolve_input(input, command)
            config = await self._resolve_config(agent, trigger, config_overrides)

            if stream_adapter == "slack":
                langchain_stream = agent.astream(
                    stream_input,
                    config=config,
                    stream_mode=["messages", "values"],
                )
                adapter = SlackStreamAdapter()
            else:
                langchain_stream = agent.astream(
                    stream_input,
                    config=config,
                    stream_mode=["messages", "values", "updates"],
                    subgraphs=True,
                )
                adapter = LangGraphStreamAdapter(subgraphs=True)

            async for chunk in adapter.stream(langchain_stream):
                yield chunk

    async def invoke(
        self,
        input: dict | None = None,
        command: dict | None = None,
        trigger: str | None = None,
        config_overrides: dict | None = None,
    ) -> dict:
        """Run the agent to completion and return the text of the last AI message."""
        async with AsyncPostgresSaver.from_conn_string(
            get_psycopg_conn_string()
        ) as checkpointer:
            agent = self._build_agent(checkpointer)
            agent_input = self._resolve_input(input, command)
            config = await self._resolve_config(agent, trigger, config_overrides)

            result = await agent.ainvoke(agent_input, config=config)

            messages = result.get("messages", [])
            last = messages[-1] if messages else None
            return {"content": _extract_text(last) if last else ""}

    def _build_deep_agent(self, checkpointer):
        """Build a deep agent with lazy sandbox backend for code execution.

        The sandbox is not created here — the LLM calls create_sandbox or
        connect_sandbox as its first tool call, which wires the lazy backend.
        """
        from app.sandbox.lazy import LazySandboxBackend
        from app.sandbox.tools import create_sandbox_tools

        lazy_backend = LazySandboxBackend()
        sandbox_tools = create_sandbox_tools(lazy_backend)

        return create_deep_agent(
            model=self.model,
            tools=[*self.agent.toolset.all, *sandbox_tools],
            system_prompt=self.agent.config.instructions or "",
            backend=lazy_backend,
            interrupt_on=self.agent.toolset.interrupt_on,
            middleware=[ToolErrorMiddleware()],
            checkpointer=checkpointer,
        )


def _extract_text(message: BaseMessage) -> str:
    """Extract the text content from an AIMessage, skipping thinking blocks."""
    content = message.content
    if isinstance(content, str):
        return content
    return "".join(
        block.get("text", "")
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    )


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
            messages.append(AIMessage(**kwargs))
        elif msg_type == "tool":
            messages.append(
                ToolMessage(
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
