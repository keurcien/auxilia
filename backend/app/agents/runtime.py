import asyncio
import logging
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from deepagents.backends import StateBackend
from deepagents.middleware.patch_tool_calls import PatchToolCallsMiddleware
from deepagents.middleware.subagents import CompiledSubAgent, SubAgentMiddleware
from langchain.agents import create_agent
from langchain.agents.middleware import (
    HumanInTheLoopMiddleware,
    ModelRetryMiddleware,
    ToolCallLimitMiddleware,
)
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    convert_to_messages,
)
from langgraph.errors import GraphRecursionError
from langgraph.types import Command
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.core.repository import AgentRepository
from app.agents.current_date import CurrentDateMiddleware
from app.agents.harness import (
    HARNESS_CONFIG,
    harness_middleware,
    harness_system_prompt,
    harness_trailing_middleware,
)
from app.agents.run_spec import AgentSpec
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
from app.agents.toolset import (
    MCPResolutionScope,
    PreparedToolset,
    Toolset,
    sanitize_tool_name,
)
from app.database import get_checkpointer
from app.exceptions import DomainValidationError, NotFoundError
from app.integrations.langfuse.callback import get_langfuse_callback_handler
from app.model_providers.catalog import ChatModelFactory
from app.model_providers.service import ModelService
from app.sandbox.lazy import LazySandboxBackend
from app.sandbox.provider import BaseSandboxProvider, build_provider
from app.threads.models import ThreadDB


logger = logging.getLogger(__name__)


# LangGraph's default recursion limit — what a subagent actually runs under,
# since the deepagents task tool builds a fresh config without ours.
SUBAGENT_RECURSION_LIMIT = 25

RECURSION_LIMIT_MESSAGE = (
    "I reached my step limit for this turn. Send any follow-up message "
    '(e.g. "continue") and I\'ll pick up where I left off.'
)


async def get_regeneration_checkpoint_id(agent, config: dict) -> str | None:
    """The checkpoint to fork from when regenerating the last answer.

    That is the state as it was before the last user message was applied — the
    turn's ``source="input"`` checkpoint, which holds the message as a pending
    write rather than in its values. Asking the checkpointer for that one
    directly is a single state load; counting human messages backwards through
    the history was one full-state deserialization per step of the last turn.
    """
    async for state in agent.aget_state_history(
        config, filter={"source": "input"}, limit=1
    ):
        return state.config["configurable"]["checkpoint_id"]
    return None


def build_runnable(
    *,
    model,
    tools,
    system_prompt,
    sandbox_backend=None,
    sandbox_provider: BaseSandboxProvider | None = None,
    base_middleware=(),
    subagents=None,
    checkpointer=None,
    output_schema: dict | None = None,
    format_mode: str = FORMAT_TOOL,
):
    """Build a LangGraph runnable. One construction path, one middleware list.

    Every agent — parent or subagent, sandboxed or not — is a ``create_agent``
    with an explicit middleware stack. A sandbox adds deepagents' harness
    (todos, filesystem, the ``task`` tool, summarization, the tool-call patcher
    and prompt caching) plus the sandbox lifecycle tools, and appends the
    harness prompt to the agent's instructions; ``app/agents/harness.py``
    assembles that bundle and ``tests/agents/test_harness_parity.py`` pins it
    to what ``create_deep_agent`` builds. Nothing else forks on the sandbox.

    ``base_middleware`` is the caller's own stack — the parent passes
    ``build_parent_middleware``'s list; subagents pass their own retry/limit/
    repair/date stack (see ``ResolvedAgent.compile``). It sits where deepagents
    puts caller middleware: after the harness, before prompt caching.

    ``DeferredStructuredOutputMiddleware`` is appended whenever an
    ``output_schema`` is given (it keeps the schema off the tool-calling loop
    and applies it on one final formatting turn). ``ToolErrorMiddleware`` is
    always appended: without it the ToolNode has no tool-call wrapper, and
    langgraph's default handler re-raises any exception that isn't a
    ``ToolInvocationError`` — an MCP transport failure in a tool (or in a
    subagent reached through ``task``) would then kill the whole run instead of
    feeding back to the model as an error ToolMessage.

    ``subagents`` (already-compiled ``CompiledSubAgent`` runnables) wire in
    through ``SubAgentMiddleware`` either way: the harness builds it, and
    without a sandbox it is added here over the in-state filesystem.
    """
    tools = list(tools)
    harness: list = []

    if sandbox_backend is not None:
        from app.sandbox.tools import create_sandbox_tools

        tools += create_sandbox_tools(sandbox_backend, sandbox_provider)
        # The general-purpose subagent inherits the parent's tools, so the
        # harness has to see the sandbox tools too — assemble it after the
        # toolset is complete.
        harness += harness_middleware(
            model=model,
            tools=tools,
            backend=sandbox_backend,
            subagents=subagents,
        )
        system_prompt = harness_system_prompt(model, system_prompt)
        # The harness brings its own PatchToolCallsMiddleware and langchain
        # asserts against duplicates, so the caller's copy is dropped.
        base_middleware = [
            m for m in base_middleware if not isinstance(m, PatchToolCallsMiddleware)
        ]

    middleware = [*harness, *base_middleware]
    if sandbox_backend is None and subagents:
        # Deliberately on the far side of the caller's stack, where the plain
        # path has always put it — the harness wires its own SubAgentMiddleware
        # *before* the caller's, because that is where deepagents puts it. Both
        # positions are load-bearing: a middleware's system-prompt fragment
        # lands in list order, so moving this one rewrites the prompt (and
        # thread prompts are frozen at creation).
        middleware.append(SubAgentMiddleware(backend=StateBackend, subagents=subagents))
    if output_schema is not None:
        middleware.append(DeferredStructuredOutputMiddleware(format_mode))
    middleware.append(ToolErrorMiddleware())
    if sandbox_backend is not None:
        middleware += harness_trailing_middleware(model)

    agent = create_agent(
        model=model,
        tools=tools,
        system_prompt=system_prompt,
        checkpointer=checkpointer,
        middleware=middleware,
        response_format=output_schema,
    )
    # deepagents binds this onto every graph it builds; keep it on the sandbox
    # path so a subagent invoked by `task` keeps the recursion budget it had.
    return agent.with_config(HARNESS_CONFIG) if sandbox_backend is not None else agent


def build_agent_middleware(
    created_at: datetime,
    *,
    recursion_limit: int,
    interrupt_on: dict[str, bool] | None = None,
) -> list:
    """The middleware stack every agent gets, parent or subagent.

    Order is load-bearing. PatchToolCallsMiddleware runs first so that any
    dangling tool_calls left by a previous aborted turn (recursion limit,
    cancelled stream, etc.) get synthetic ToolMessage responses before the model
    sees them. ModelRetryMiddleware is listed early so a retry re-runs the whole
    inner pipeline (date stamp, deferred formatting); it retries transient model
    failures (rate limits, timeouts, connection drops — classified via
    ``ModelError.is_retryable``) and, when retries are exhausted, persists the
    failure as an AIMessage so the turn ends visibly instead of crashing.
    Non-retryable errors (e.g. provider 400s) re-raise immediately and surface
    through the run record. RepairInvalidToolCallsMiddleware is placed *before*
    HITL so it runs *after* it (after_model hooks execute last-to-first): HITL
    must see only the genuine tool_calls and gate those, while the malformed
    calls stay in invalid_tool_calls (invisible to HITL) until Repair promotes
    them into tool_calls answered by error ToolMessages.

    Parent and subagent differ in exactly two documented ways:

    - ``interrupt_on`` — a mapping (even an empty one) means this agent runs
      against a checkpointer, so it can be interrupted for approval and can
      have dangling tool calls persisted by an aborted turn. A subagent has
      neither: the deepagents ``task`` tool invokes CompiledSubAgent runnables
      with a fresh config and no checkpointer, so it passes ``None`` and loses
      both the approval gate and the patcher. Approval gates on subagent tools
      being silently dropped is a known product gap: issue #301.
    - ``recursion_limit`` — the tool budget is sized to end the run gracefully
      one step before the graph's own recursion limit trips. A subagent runs
      under langgraph's default (``SUBAGENT_RECURSION_LIMIT``) rather than
      ours, because ``task`` doesn't propagate the parent's config.
    """
    checkpointed = interrupt_on is not None
    return [
        *([PatchToolCallsMiddleware()] if checkpointed else []),
        ModelRetryMiddleware(),
        ToolCallLimitMiddleware(
            run_limit=(recursion_limit - 1) // 2, exit_behavior="end"
        ),
        RepairInvalidToolCallsMiddleware(),
        *(
            [
                HumanInTheLoopMiddleware(
                    interrupt_on=interrupt_on,
                    description_prefix="Tool execution pending approval",
                )
            ]
            if checkpointed
            else []
        ),
        CurrentDateMiddleware(created_at),
    ]


def build_parent_middleware(created_at: datetime, prepared: PreparedToolset) -> list:
    """The parent agent's stack: checkpointed, under our own recursion limit."""
    return build_agent_middleware(
        created_at,
        recursion_limit=agent_settings.recursion_limit,
        interrupt_on=prepared.interrupt_on,
    )


@dataclass
class ResolvedSandbox:
    """An agent's sandbox binding, resolved to a ready provider: the row is
    loaded and its credential decrypted at request scope, so the streaming
    scope (and subagent compile) never touch the DB or a global."""

    provider: BaseSandboxProvider
    tools: dict | None


@dataclass
class ResolvedAgent:
    """An agent config with its prepared toolset. Used for both parent and subagents.

    ``prepared`` is built at request scope (all DB work). ``live`` is populated
    inside the streaming scope (``Agent._setup``) with tools bound to a persistent
    per-server MCP session, and is the toolset actually handed to the LLM.
    """

    config: AgentSpec
    prepared: PreparedToolset
    live: Toolset | None = None
    sandbox: ResolvedSandbox | None = None

    @classmethod
    async def resolve(
        cls,
        spec: AgentSpec,
        db: AsyncSession,
        user_id: str,
        *,
        is_parent: bool = False,
        scope: MCPResolutionScope | None = None,
    ) -> "ResolvedAgent":
        """Bind one agent's spec to a prepared toolset.

        Takes an already-read `AgentSpec` rather than an id: the whole graph
        comes from a single `get_run_spec`, so resolving a subagent costs no
        further agent queries (design review §2.2). It also keeps the runtime
        off `AgentService`/`AgentResponse` — the run path has no business
        depending on API response assembly.

        `scope` carries the graph's MCP server rows, read once by `Agent.build`
        for the parent and every subagent together.
        """
        prepared = await Toolset.prepare(
            spec.mcp_servers, db, user_id, apply_ui=is_parent, scope=scope
        )
        return cls(config=spec, prepared=prepared, sandbox=cls._resolve_sandbox(spec))

    @staticmethod
    def _resolve_sandbox(spec: AgentSpec) -> ResolvedSandbox | None:
        if spec.sandbox is None:
            return None
        row = spec.sandbox.row
        try:
            provider = build_provider(row)
        except Exception:
            # A row that no longer validates (e.g. secret cleared) must not
            # kill the whole run — the agent just runs without code execution.
            logger.exception("Failed to build sandbox provider %s", row.id)
            return None
        return ResolvedSandbox(provider=provider, tools=spec.sandbox.tools)

    def compile(self, model, created_at: datetime) -> CompiledSubAgent:
        """Compile into a CompiledSubAgent runnable (for subagent use).

        ``created_at`` is the thread's creation date, stamped onto the
        subagent's system prompt by ``CurrentDateMiddleware``.

        A subagent gets its own copy of the shared middleware stack rather than
        inheriting the parent's: the deepagents ``task`` tool invokes it with a
        fresh config (parent middleware and recursion_limit don't propagate)
        and reports back only ``messages[-1].text``, so a subagent that exits
        its loop silently (invalid tool-call JSON) would return an empty
        ToolMessage and one that blows the recursion limit would discard its
        progress. It runs without a checkpointer, which is what drops the
        approval gate — see ``build_agent_middleware`` for both differences.
        """
        sandbox = self.sandbox is not None
        # Subagent sandboxes get no turn-end persist hook: CompiledSubAgent
        # runnables have no teardown point, so whatever a subagent writes is
        # lost when its `task` call ends — issue #302.
        runnable = build_runnable(
            model=model,
            tools=self.live.all,
            system_prompt=self.config.instructions or "",
            sandbox_backend=LazySandboxBackend() if sandbox else None,
            sandbox_provider=self.sandbox.provider if self.sandbox else None,
            base_middleware=build_agent_middleware(
                created_at, recursion_limit=SUBAGENT_RECURSION_LIMIT
            ),
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
        provider: str | None = None,
    ):
        self.thread = thread
        self.agent = agent
        self.model = model
        self.middleware = middleware
        self.callbacks = callbacks
        self.subagents = subagents
        self._sandbox_backend: LazySandboxBackend | None = None
        self.provider = provider

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

        # One read for the whole graph. This used to be a full `AgentService.get`
        # per agent, run sequentially for subagents (§1.2): ~8 + 7N round-trips
        # before the first token.
        spec = await AgentRepository(db).get_run_spec(thread.agent_id)
        if spec is None:
            raise NotFoundError("Agent not found")

        # Every MCP server the graph touches, in one query — the parent's and
        # each subagent's (design review §2.2 / P2-6).
        scope = await MCPResolutionScope.build(spec.all_mcp_bindings, db, user_id)
        agent = await ResolvedAgent.resolve(
            spec.agent, db, user_id, is_parent=True, scope=scope
        )

        # Backstop for the RunService.create gate: covers the race where the
        # model is disabled between enqueue and worker pickup, and any future
        # path that builds an agent without going through `create`.
        resolved = await ModelService(db).ensure_available(
            thread.model_id, reasoning_effort=thread.reasoning_effort
        )
        model = ChatModelFactory().create(
            resolved.provider,
            resolved.model_id,
            resolved.api_key,
            reasoning_effort=resolved.reasoning_effort,
        )

        middleware = build_parent_middleware(thread.created_at, agent.prepared)

        # Still sequential, and deliberately so: these share one AsyncSession,
        # which is not concurrency-safe. It no longer costs anything to be —
        # `get_run_spec` read the agent rows and `scope` the MCP ones, so each
        # resolve is Redis/CPU work over rows already in hand.
        subagents = [
            await ResolvedAgent.resolve(sub, db, user_id, scope=scope)
            for sub in spec.subagents
        ]

        handler = get_langfuse_callback_handler()
        callbacks = [handler] if handler is not None else []

        return cls(
            thread=thread,
            agent=agent,
            model=model,
            middleware=middleware,
            callbacks=callbacks,
            subagents=subagents,
            provider=resolved.provider,
        )

    def _build_agent(self, checkpointer, output_schema: dict | None = None):
        """Build the LangGraph agent (deep or standard) with the given checkpointer.

        `output_schema` is a raw JSON Schema dict passed to langchain as
        `response_format`. DeferredStructuredOutputMiddleware keeps the schema
        off the tool-calling loop and applies it on one final formatting turn;
        the parsed result surfaces in the run state under `structured_response`.
        """
        sandbox = self.agent.sandbox is not None
        self._sandbox_backend = LazySandboxBackend() if sandbox else None
        compiled = (
            [s.compile(self.model, self.thread.created_at) for s in self.subagents]
            if self.subagents
            else None
        )
        return build_runnable(
            model=self.model,
            tools=self.agent.live.all,
            system_prompt=self.agent.config.instructions or "",
            sandbox_backend=self._sandbox_backend,
            sandbox_provider=self.agent.sandbox.provider
            if self.agent.sandbox
            else None,
            base_middleware=self.middleware,
            subagents=compiled,
            checkpointer=checkpointer,
            output_schema=output_schema,
            format_mode=PROVIDER_FORMAT_MODES.get(self.provider, FORMAT_TOOL),
        )

    def _resolve_input(self, agent_input: dict | None, command: dict | None):
        """Resolve raw input/command dicts into the value to pass to the agent.

        The message dicts come from a client (the chat UI, a trigger, Slack), so
        a malformed one is a bad request, not a server fault — `convert_to_messages`
        rejects an unknown role instead of silently filing it as a user turn.
        It signals rejection with whatever fits the shape it was handed:
        `ValueError` for an unknown role or a dict missing `content`,
        `NotImplementedError` for an item that is not a message at all (a bare
        number, `None`, a nested list). All of them are the client's fault.
        """
        if command is not None:
            return Command(resume=command.get("resume"))
        raw = agent_input.get("messages", []) if agent_input else []
        if not isinstance(raw, list):
            raise DomainValidationError("Invalid run input: `messages` must be a list")
        try:
            messages = convert_to_messages(raw)
        except (ValueError, TypeError, KeyError, NotImplementedError) as e:
            raise DomainValidationError(f"Invalid run input: {e}") from e
        return {"messages": messages}

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

    async def _persist_sandbox(self) -> None:
        """Snapshot the sandbox state at turn end, if one was used.

        Cloud Run sandboxes live inside a single instance, so their overlay is
        exported to GCS here for cross-instance reconnects; OpenSandbox's
        persist is a no-op. Failures are logged, never raised — a snapshot
        problem must not mask the run's result.
        """
        backend = self._sandbox_backend
        if backend is None or not backend.connected:
            return
        try:
            await asyncio.to_thread(backend.persist)
        except Exception:
            logger.exception("Failed to persist sandbox state")

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
            finally:
                await self._persist_sandbox()


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
