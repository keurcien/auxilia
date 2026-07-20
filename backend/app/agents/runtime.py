import asyncio
import logging
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from uuid import uuid4

from deepagents import create_deep_agent
from deepagents.backends import StateBackend
from deepagents.middleware.patch_tool_calls import PatchToolCallsMiddleware
from deepagents.middleware.subagents import CompiledSubAgent, SubAgentMiddleware
from langchain.agents import create_agent
from langchain.agents.middleware import (
    HumanInTheLoopMiddleware,
    ToolCallLimitMiddleware,
)
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.errors import GraphRecursionError
from langgraph.types import Command
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.core.service import AgentService
from app.agents.schemas import AgentResponse
from app.agents.settings import agent_settings
from app.agents.stream import (
    LangGraphStreamAdapter,
    encode_synthetic_ai_message_sse,
)
from app.agents.structured_output import (
    FORMAT_TOOL,
    PROVIDER_FORMAT_MODES,
    DeferredStructuredOutputMiddleware,
    is_structured_output_artifact,
)
from app.agents.tool_errors import RepairInvalidToolCallsMiddleware, ToolErrorMiddleware
from app.agents.toolset import PreparedToolset, Toolset, sanitize_tool_name
from app.database import get_checkpointer
from app.exceptions import DomainValidationError
from app.integrations.langfuse.callback import langfuse_callback_handler
from app.model_providers.catalog import (
    LLM_PROVIDERS,
    MODELS,
    ChatModelFactory,
)
from app.sandbox.settings import sandbox_settings
from app.threads.models import ThreadDB


logger = logging.getLogger(__name__)


RECURSION_LIMIT_MESSAGE = (
    "I reached my step limit for this turn. Send any follow-up message "
    '(e.g. "continue") and I\'ll pick up where I left off.'
)


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


def build_runnable(
    *,
    model,
    tools,
    system_prompt,
    sandbox: bool,
    base_middleware=(),
    subagents=None,
    checkpointer=None,
    output_schema: dict | None = None,
    format_mode: str = FORMAT_TOOL,
):
    """Build a LangGraph runnable, dispatching on whether a sandbox is needed.

    Single construction path for both the parent agent and subagents. The
    no-sandbox branch uses a plain ``create_agent`` (so simple agents avoid
    deepagents' always-on filesystem/todo/patch scaffolding); the sandbox branch
    uses ``create_deep_agent`` with a lazy sandbox backend (the sandbox itself is
    created on first tool call, not here).

    ``base_middleware`` is the caller's middleware stack — the parent passes its
    full stack; subagents pass nothing. ``DeferredStructuredOutputMiddleware`` is
    appended whenever an ``output_schema`` is given (it keeps the schema off the
    tool-calling loop and applies it on one final formatting turn). On the
    sandbox path ``ToolErrorMiddleware`` is appended and the caller's
    ``PatchToolCallsMiddleware`` is dropped, since ``create_deep_agent`` injects
    its own and langchain asserts against duplicates.

    ``subagents`` (already-compiled ``CompiledSubAgent`` runnables) wire in via
    ``SubAgentMiddleware`` on the no-sandbox path and via the ``subagents=`` arg
    on the sandbox path.
    """
    if sandbox:
        from app.sandbox.lazy import LazySandboxBackend
        from app.sandbox.tools import create_sandbox_tools

        lazy_backend = LazySandboxBackend()
        middleware = [
            m for m in base_middleware if not isinstance(m, PatchToolCallsMiddleware)
        ]
        if output_schema is not None:
            middleware.append(DeferredStructuredOutputMiddleware(format_mode))
        return create_deep_agent(
            model=model,
            tools=[*tools, *create_sandbox_tools(lazy_backend)],
            system_prompt=system_prompt,
            backend=lazy_backend,
            middleware=[*middleware, ToolErrorMiddleware()],
            subagents=subagents,
            checkpointer=checkpointer,
            response_format=output_schema,
        )

    middleware = list(base_middleware)
    if subagents:
        middleware.append(SubAgentMiddleware(backend=StateBackend, subagents=subagents))
    if output_schema is not None:
        middleware.append(DeferredStructuredOutputMiddleware(format_mode))
    return create_agent(
        model=model,
        tools=tools,
        system_prompt=system_prompt,
        checkpointer=checkpointer,
        middleware=middleware,
        response_format=output_schema,
    )


@dataclass
class ResolvedAgent:
    """An agent config with its prepared toolset. Used for both parent and subagents.

    ``prepared`` is built at request scope (all DB work). ``live`` is populated
    inside the streaming scope (``Agent._setup``) with tools bound to a persistent
    per-server MCP session, and is the toolset actually handed to the LLM.
    """

    config: AgentResponse
    prepared: PreparedToolset
    live: Toolset | None = None

    @classmethod
    async def resolve(
        cls,
        agent_id,
        db: AsyncSession,
        user_id: str,
        *,
        is_parent: bool = False,
    ) -> "ResolvedAgent":
        config = await AgentService(db).get(agent_id, include_archived=True)
        prepared = await Toolset.prepare(
            config.mcp_servers, db, user_id, apply_ui=is_parent
        )
        return cls(config=config, prepared=prepared)

    def compile(self, model) -> CompiledSubAgent:
        """Compile into a CompiledSubAgent runnable (for subagent use).

        Subagent-level HITL is intentionally not wired here: CompiledSubAgent
        runnables don't inherit the parent's checkpointer, and HumanInTheLoopMiddleware
        needs one. Approval gates on subagent tools are silently dropped today.
        """
        sandbox = self.config.has_code_interpreter and sandbox_settings.enabled
        system_prompt = (
            self.config.instructions or ""
            if sandbox
            else SystemMessage(
                content=[{"type": "text", "text": self.config.instructions or ""}]
            )
        )
        runnable = build_runnable(
            model=model,
            tools=self.live.all,
            system_prompt=system_prompt,
            sandbox=sandbox,
        )
        return CompiledSubAgent(
            name=sanitize_tool_name(self.config.name),
            description=f"{self.config.name}: {self.config.description or self.config.name}",
            runnable=runnable,
        )


class Agent:
    def __init__(
        self,
        thread: ThreadDB,
        agent: ResolvedAgent,
        model,
        middleware: list,
        callbacks: list,
        subagents: list[ResolvedAgent],
    ):
        self.thread = thread
        self.agent = agent
        self.model = model
        self.middleware = middleware
        self.callbacks = callbacks
        self.subagents = subagents

    @property
    def metadata(self) -> dict:
        return {
            "user_id": self.thread.user_id,
            "thread_id": self.thread.id,
            "agent_id": self.thread.agent_id,
            "langfuse_session_id": self.thread.id,
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
    ) -> "Agent":
        user_id = str(thread.user_id)

        agent = await ResolvedAgent.resolve(
            thread.agent_id, db, user_id, is_parent=True
        )

        model_entry = next((m for m in MODELS if m.name == thread.model_id), None)
        if model_entry is None:
            raise DomainValidationError(f"Unknown model: {thread.model_id}")
        provider = next(
            (p for p in LLM_PROVIDERS if p.name == model_entry.provider), None
        )
        if provider is None:
            raise DomainValidationError(
                f"Unknown provider {model_entry.provider!r} for model {thread.model_id}"
            )
        model = ChatModelFactory().create(
            provider.name, thread.model_id, provider.api_key
        )

        # Build middleware stack.
        # PatchToolCallsMiddleware runs first so that any dangling tool_calls
        # left by a previous aborted turn (recursion limit, cancelled stream,
        # etc.) get synthetic ToolMessage responses before the model sees them.
        # RepairInvalidToolCallsMiddleware is placed *before* HITL so it runs
        # *after* it (after_model hooks execute last-to-first): HITL must see only
        # the genuine tool_calls and gate those, while the malformed calls stay in
        # invalid_tool_calls (invisible to HITL) until Repair promotes them into
        # tool_calls answered by error ToolMessages.
        middleware = [
            PatchToolCallsMiddleware(),
            ToolCallLimitMiddleware(
                run_limit=(agent_settings.recursion_limit - 1) // 2, exit_behavior="end"
            ),
            RepairInvalidToolCallsMiddleware(),
            HumanInTheLoopMiddleware(
                interrupt_on=agent.prepared.interrupt_on,
                description_prefix="Tool execution pending approval",
            ),
        ]

        subagents: list[ResolvedAgent] = []
        if agent.config.subagents:
            for sub in agent.config.subagents:
                subagents.append(await ResolvedAgent.resolve(sub.id, db, user_id))

        callbacks = (
            [langfuse_callback_handler] if langfuse_callback_handler is not None else []
        )

        return cls(
            thread=thread,
            agent=agent,
            model=model,
            middleware=middleware,
            callbacks=callbacks,
            subagents=subagents,
        )

    def _build_agent(self, checkpointer, output_schema: dict | None = None):
        """Build the LangGraph agent (deep or standard) with the given checkpointer.

        `output_schema` is a raw JSON Schema dict passed to langchain as
        `response_format`. DeferredStructuredOutputMiddleware keeps the schema
        off the tool-calling loop and applies it on one final formatting turn;
        the parsed result surfaces in the run state under `structured_response`.
        """
        sandbox = self.agent.config.has_code_interpreter and sandbox_settings.enabled
        compiled = (
            [s.compile(self.model) for s in self.subagents] if self.subagents else None
        )
        # Deep agents take the raw instruction string; create_agent takes a
        # SystemMessage. Keep each form as-is to avoid a prompt-shape change.
        system_prompt = (
            self.agent.config.instructions or ""
            if sandbox
            else SystemMessage(self.agent.config.instructions)
        )
        provider = next(
            (m.provider for m in MODELS if m.name == self.thread.model_id), None
        )
        return build_runnable(
            model=self.model,
            tools=self.agent.live.all,
            system_prompt=system_prompt,
            sandbox=sandbox,
            base_middleware=self.middleware,
            subagents=compiled,
            checkpointer=checkpointer,
            output_schema=output_schema,
            format_mode=PROVIDER_FORMAT_MODES.get(provider, FORMAT_TOOL),
        )

    def _resolve_input(self, agent_input: dict | None, command: dict | None):
        """Resolve raw input/command dicts into the value to pass to the agent."""
        if command is not None:
            return Command(resume=command.get("resume"))
        lc_messages = _dicts_to_lc_messages(
            agent_input.get("messages", []) if agent_input else []
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

    @asynccontextmanager
    async def _setup(
        self,
        agent_input: dict | None,
        command: dict | None,
        trigger: str | None,
        config_overrides: dict | None,
        output_schema: dict | None = None,
    ):
        """Open a checkpointer scope and yield (agent, resolved_input, config).

        Scaffolding for `stream`: opens one persistent MCP
        session per server (parent + subagents) on an AsyncExitStack that lives for
        the whole astream/ainvoke loop, opens the AsyncPostgresSaver, builds the
        LangGraph agent against the live tools, and resolves the request input and
        run config in one place.
        """
        async with AsyncExitStack() as stack, get_checkpointer() as checkpointer:
            # Open every toolset (parent + subagents) concurrently.
            # return_exceptions=True so all enters finish before we
            # proceed or raise — a bare gather would orphan in-flight
            # session opens past the stack's unwind on first failure.
            resolved = [self.agent, *self.subagents]
            results = await asyncio.gather(
                *(
                    stack.enter_async_context(Toolset.open(ra.prepared))
                    for ra in resolved
                ),
                return_exceptions=True,
            )
            for result in results:
                if isinstance(result, BaseException):
                    raise result
            for ra, live in zip(resolved, results, strict=True):
                ra.live = live
            agent = self._build_agent(checkpointer, output_schema)
            resolved_input = self._resolve_input(agent_input, command)
            config = await self._resolve_config(agent, trigger, config_overrides)
            yield agent, resolved_input, config

    async def _persist_recursion_fallback(self, agent, config) -> AIMessage:
        """Persist a synthetic AI message after a GraphRecursionError so the
        next turn can pick up where we left off. Returns the message."""
        logger.info("Graph recursion limit reached; persisting synthetic AI message")
        ai_msg = AIMessage(content=RECURSION_LIMIT_MESSAGE, id=str(uuid4()))
        await agent.aupdate_state(config, {"messages": [ai_msg]})
        return ai_msg

    async def stream(
        self,
        agent_input: dict | None = None,
        command: dict | None = None,
        trigger: str | None = None,
        config_overrides: dict | None = None,
        output_schema: dict | None = None,
    ):
        """Stream using the native LangGraph SSE protocol.

        Args:
            agent_input: Graph input dict (e.g. {"messages": [{"type": "human", ...}]}) or None for resume.
            command: LangGraph Command dict (e.g. {"resume": {...}}) for HITL resume.
            trigger: Optional trigger ("regenerate-message") for regeneration.
            config_overrides: Optional config dict with configurable overrides.
            output_schema: Optional JSON Schema; when set, the run produces a
                `structured_response` in its final state (read via `read_run_result`).
        """
        async with self._setup(
            agent_input, command, trigger, config_overrides, output_schema
        ) as (
            agent,
            stream_input,
            config,
        ):
            if output_schema is not None and command is None:
                # `structured_response` is a persistent channel: if this turn's
                # formatting never runs (e.g. recursion fallback), a previous
                # turn's value would otherwise be read back as this run's result.
                state = await agent.aget_state(config)
                if state.values.get("structured_response") is not None:
                    await agent.aupdate_state(config, {"structured_response": None})
            langchain_stream = agent.astream(
                stream_input,
                config=config,
                stream_mode=["messages", "values", "updates"],
                subgraphs=True,
            )
            adapter = LangGraphStreamAdapter(subgraphs=True)

            try:
                async for chunk in adapter.stream(langchain_stream):
                    yield chunk
            except GraphRecursionError:
                ai_msg = await self._persist_recursion_fallback(agent, config)
                state = await agent.aget_state(config)
                for sse in encode_synthetic_ai_message_sse(ai_msg, state.values):
                    yield sse


def extract_invoke_result(
    messages: list, structured_response: dict | None = None
) -> dict:
    """Project a turn's final messages into the invoke response shape.

    Skips formatting-turn artifacts so `content` is the prose answer on every
    provider path; the parsed object travels in its own field. Used by the
    durable path's `read_run_result`.
    """
    last = next(
        (m for m in reversed(messages) if not is_structured_output_artifact(m)),
        None,
    )
    return {
        "content": _extract_text(last) if last else "",
        "structured_response": structured_response,
    }


async def read_run_result(thread_id: str) -> dict:
    """Read a thread's final-turn result from its checkpoint (out-of-request).

    The durable runtime streams a run to its event log rather than returning a
    value, so the synchronous `/runs/invoke` consumer reads the answer back from
    the LangGraph checkpoint once the run is terminal.
    """
    async with get_checkpointer() as checkpointer:
        checkpoint = await checkpointer.aget_tuple(
            config={"configurable": {"thread_id": thread_id}}
        )
    if checkpoint is None:
        return {"content": "", "structured_response": None}
    channel_values = checkpoint.checkpoint["channel_values"]
    return extract_invoke_result(
        channel_values.get("messages", []),
        channel_values.get("structured_response"),
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
