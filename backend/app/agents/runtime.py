import asyncio
import logging
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4

from deepagents.backends import StateBackend
from deepagents.graph import DeepAgentState
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
    HumanMessage,
    convert_to_messages,
)
from langgraph.errors import GraphRecursionError
from langgraph.stream.transformers import UpdatesTransformer
from langgraph.types import Command
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.checkpoints import get_checkpoint_state
from app.agents.core.repository import AgentRepository
from app.agents.current_date import CurrentDateMiddleware
from app.agents.harness import (
    HARNESS_CONFIG,
    harness_middleware,
    harness_system_prompt,
    harness_trailing_middleware,
)
from app.agents.protocol.emit import ProtocolEmitter
from app.agents.run_spec import AgentSpec
from app.agents.settings import agent_settings
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
from app.database import AsyncSessionLocal, get_checkpointer
from app.exceptions import DomainValidationError, NotFoundError
from app.integrations.langfuse.callback import get_langfuse_callback_handler
from app.model_providers.catalog import ChatModelFactory
from app.model_providers.service import ModelService
from app.sandbox.provider import (
    BaseSandboxProvider,
    SandboxSession,
    build_provider,
    open_sandbox,
)
from app.skills.runtime import (
    SKILLS_ROOT,
    materialize_skills,
    merge_catalogs,
    skill_files,
    skills_sources,
)
from app.threads.models import ThreadDB
from app.threads.repository import ThreadRepository


logger = logging.getLogger(__name__)


RECURSION_LIMIT_MESSAGE = (
    "I reached my step limit for this turn. Send any follow-up message "
    '(e.g. "continue") and I\'ll pick up where I left off.'
)


@dataclass(frozen=True)
class RegenerationPoint:
    """Where a regeneration restarts the thread from, and with what.

    ``checkpoint_id`` is the checkpoint to fork from — the last one *before*
    the turn being redone. ``None`` means the turn being redone was the
    thread's first, so there is nothing earlier to fork from and the thread
    restarts from scratch instead. ``message`` is the user message that
    opened the turn, re-sent as the fork's input under its original id.
    """

    checkpoint_id: str | None
    message: HumanMessage | None


async def get_regeneration_point(agent, config: dict) -> RegenerationPoint | None:
    """Where to restart from when regenerating the last answer, or ``None``
    when the thread has no turn to redo.

    The turn's ``source="input"`` checkpoint is found in one history read; it
    holds the user's message as a pending write. The fork target is that
    checkpoint's **parent** — the end of the previous turn — not the input
    checkpoint itself, and the message is re-sent as fresh input. Forking from
    the input checkpoint would be the obvious choice and is wrong under
    ``DeepAgentState``: langgraph copies the loaded checkpoint's pending
    writes onto the fork checkpoint it creates, and the ``DeltaChannel``
    replay then sees the user's message twice — once under each — so every
    later turn (and every reader) shows the question duplicated. The parent
    has no pending writes, so nothing is copied. Under ``add_messages`` both
    forks are equivalent, since it forks from stored values, not writes.
    """
    async for state in agent.aget_state_history(
        config, filter={"source": "input"}, limit=1
    ):
        # The input snapshot's values are the state *before* the message was
        # applied (it sits in the snapshot's pending writes), so the turn's
        # message is read off the thread's latest state instead: its last
        # human message.
        latest = await agent.aget_state(config)
        message = next(
            (
                m
                for m in reversed(latest.values.get("messages", []))
                if isinstance(m, HumanMessage)
            ),
            None,
        )
        parent = state.parent_config
        if parent is None:
            return RegenerationPoint(checkpoint_id=None, message=message)
        return RegenerationPoint(
            checkpoint_id=parent["configurable"]["checkpoint_id"], message=message
        )
    return None


def build_runnable(
    *,
    model,
    tools,
    system_prompt,
    sandbox_backend=None,
    skills=None,
    skill_files=None,
    base_middleware=(),
    subagents=None,
    checkpointer=None,
    output_schema: dict | None = None,
    format_mode: str = FORMAT_TOOL,
):
    """Build a LangGraph runnable. One construction path, one middleware list.

    Every agent — parent or subagent, sandboxed or not — is a ``create_agent``
    with an explicit middleware stack. A sandbox adds deepagents' harness
    (todos, skills, filesystem, the ``task`` tool, summarization, the tool-call
    patcher and prompt caching) and appends the harness prompt to the agent's
    instructions; ``app/agents/harness.py`` assembles that bundle and
    ``tests/agents/test_harness_parity.py`` pins it to what ``create_deep_agent``
    builds. Nothing else forks on the sandbox.

    ``sandbox_backend`` is a *live* sandbox — the runtime connects it before
    the graph is built (``Agent._setup``); the model never creates or
    reconnects one. ``skills`` are ``SkillsMiddleware`` sources; without a
    sandbox the ``skill_files`` are placed in the agent's own state and read
    with only the two read tools — no host filesystem, no process.

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

    Every graph is compiled with deepagents' ``DeepAgentState``: its
    ``messages`` channel is a ``DeltaChannel``, so a checkpoint stores the
    step's writes rather than the whole conversation (O(N) growth over a
    thread instead of O(N²)). deepagents only does this for the deep agent;
    plain agents and subagents have the same long threads, so they get it
    too. The price is that ``channel_values["messages"]`` is no longer
    readable raw — every out-of-request reader goes through
    ``app.agents.checkpoints.get_checkpoint_state``.
    """
    tools = list(tools)
    harness: list = []

    if sandbox_backend is not None:
        harness += harness_middleware(
            model=model,
            tools=tools,
            backend=sandbox_backend,
            subagents=subagents,
            skills=skills,
        )
        system_prompt = harness_system_prompt(model, system_prompt)
        # The harness brings its own PatchToolCallsMiddleware and langchain
        # asserts against duplicates, so the caller's copy is dropped.
        base_middleware = [
            m for m in base_middleware if not isinstance(m, PatchToolCallsMiddleware)
        ]

    elif skills is not None:
        from app.skills.middleware import skills_read_middleware

        (root, _label), *_ = skills
        harness += skills_read_middleware(root, skill_files or [], skills)

    middleware = [*harness, *base_middleware]
    if sandbox_backend is None and subagents:
        # On the far side of the caller's stack, where the plain path has
        # always put it — the harness wires its own SubAgentMiddleware *before*
        # the caller's, because that is where deepagents puts it. Since
        # deepagents 0.7 the middleware injects no system-prompt fragment of
        # its own (the `task` tool description carries the agent list), so the
        # position only orders hooks now.
        middleware.append(
            SubAgentMiddleware(backend=StateBackend(), subagents=subagents)
        )
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
        state_schema=DeepAgentState,
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

    ``interrupt_on`` — a mapping (even an empty one) means this agent runs
    against a checkpointer, so it can be interrupted for approval and can have
    dangling tool calls persisted by an aborted turn; ``None`` drops both the
    approval gate and the patcher. Parent *and* subagents are checkpointed:
    the deepagents ``task`` tool spreads the parent's ``configurable`` into the
    subagent, which carries the checkpointer and the ``tools:<task-id>``
    namespace, so a subagent's interrupt propagates to the root checkpoint
    (with an id that encodes its namespace) and an id-keyed resume routes back
    into it — see ``app/agents/hitl.py``. Only tests and the structured-output
    formatting turn pass ``None``.

    ``recursion_limit`` — the tool budget is sized to end the run gracefully
    one step before the graph's own recursion limit trips. A subagent runs
    under the same limit as its parent: the ``task`` tool invokes it inside
    the parent's tool node, and langgraph seeds the nested run from that
    ambient config, ``recursion_limit`` included (on the sandbox path the
    graph's bound ``HARNESS_CONFIG`` then wins the merge, so the tool budget
    is the limit that actually ends the run).
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
    skills: dict = field(default_factory=dict)

    @classmethod
    async def resolve(
        cls,
        spec: AgentSpec,
        db: AsyncSession,
        user_id: str,
        *,
        is_parent: bool = False,
        scope: MCPResolutionScope | None = None,
        thread_id: str | None = None,
        skill_snapshot: dict | None = None,
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
        from app.skills.runtime import resolve_skills

        skills = (
            await resolve_skills(db, spec, user_id, thread_id, skill_snapshot)
            if thread_id
            else {}
        )
        return cls(
            config=spec,
            prepared=prepared,
            sandbox=cls._resolve_sandbox(spec),
            skills=skills,
        )

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

    def skill_kwargs(self) -> dict:
        """`build_runnable`'s skills arguments for this agent: the sources, and
        the files themselves when there is no sandbox to upload them to."""
        sources = skills_sources(self.skills)
        if sources is None:
            return {"skills": None}
        files = None
        if self.sandbox is None:
            files = skill_files(self.skills, SKILLS_ROOT)
        return {"skills": sources, "skill_files": files}

    def compile(
        self,
        model,
        created_at: datetime,
        *,
        sandbox_backend=None,
    ) -> CompiledSubAgent:
        """Compile into a CompiledSubAgent runnable (for subagent use).

        ``created_at`` is the thread's creation date, stamped onto the
        subagent's system prompt by ``CurrentDateMiddleware``. ``sandbox_backend``
        is the run's live sandbox (used when this subagent is bound to one).

        A subagent gets its own copy of the shared middleware stack rather than
        inheriting the parent's: the deepagents ``task`` tool invokes it as a
        nested subgraph (parent middleware doesn't propagate; the run config —
        checkpointer, namespace, recursion limit — does) and reports back only
        the last AI message's text, so a subagent that exits its loop silently
        (invalid tool-call JSON) would return an empty ToolMessage and one that
        blows the recursion limit would discard its progress. Its own
        ``interrupt_on`` gates its tools: the interrupt surfaces on the root
        checkpoint and the web client / Slack approve it like a parent's
        (issue #301).
        """
        # A subagent bound to a sandbox shares the run's one live sandbox
        # (`sandbox_backend`), so the parent's turn-end persist covers what it
        # wrote — closing the gap of issue #302.
        runnable = build_runnable(
            model=model,
            tools=list(self.live.all),
            system_prompt=self.config.instructions or "",
            sandbox_backend=sandbox_backend if self.sandbox else None,
            **self.skill_kwargs(),
            base_middleware=build_agent_middleware(
                created_at,
                recursion_limit=agent_settings.recursion_limit,
                interrupt_on=self.prepared.interrupt_on,
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
        # Set by `_setup`, for the length of one run.
        self._sandbox: SandboxSession | None = None
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
        skill_snapshot: dict | None = None,
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
            spec.agent,
            db,
            user_id,
            is_parent=True,
            scope=scope,
            thread_id=thread.id,
            skill_snapshot=skill_snapshot.get(str(spec.agent.id), {"entries": []})
            if skill_snapshot is not None
            else None,
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
            await ResolvedAgent.resolve(
                sub,
                db,
                user_id,
                scope=scope,
                thread_id=thread.id,
                skill_snapshot=skill_snapshot.get(str(sub.id), {"entries": []})
                if skill_snapshot is not None
                else None,
            )
            for sub in spec.subagents
        ]

        # One skill set per graph: every agent lists, reads and runs the union
        # of what the supervisor and its subagents have attached.
        shared = merge_catalogs(ra.skills for ra in [agent, *subagents])
        for ra in [agent, *subagents]:
            ra.skills = shared

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
        compiled = (
            [
                s.compile(
                    self.model,
                    self.thread.created_at,
                    sandbox_backend=self._sandbox_for(s),
                )
                for s in self.subagents
            ]
            if self.subagents
            else None
        )
        return build_runnable(
            model=self.model,
            tools=list(self.agent.live.all),
            system_prompt=self.agent.config.instructions or "",
            sandbox_backend=self._sandbox_for(self.agent),
            **self.agent.skill_kwargs(),
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
        checkpointer,
        trigger: str | None,
        config_overrides: dict | None,
        resolved_input: Any,
    ) -> tuple[dict, Any]:
        """Build the run config, applying overrides and regeneration logic.

        Returns the config and the input to run with. Regenerating forks the
        thread from before its last turn (see `get_regeneration_point`) and
        re-sends the message that opened it. The client submits *no* input
        for a regeneration — the documented `submit(null, …)` shape, so it
        echoes nothing optimistically and the page keeps the question in
        place while only the answer changes — and the server supplies the
        message, under its original id, from the turn's input checkpoint. A
        client that does re-send the message (Slack, older pages) is honoured
        as-is. When the turn was the thread's first there is no earlier
        checkpoint: the thread's checkpoints are wiped and the message starts
        it over — the same outcome, with no history to fork from.
        """
        config = self._stream_config
        if config_overrides and config_overrides.get("configurable"):
            config["configurable"].update(config_overrides["configurable"])
        if trigger == "regenerate-message":
            point = await get_regeneration_point(agent, config)
            has_input = isinstance(resolved_input, dict) and bool(
                resolved_input.get("messages")
            )
            if point is None or (not has_input and point.message is None):
                if not has_input:
                    raise DomainValidationError("Nothing to regenerate on this thread.")
            else:
                if not has_input:
                    resolved_input = {"messages": [point.message]}
                if point.checkpoint_id is None:
                    await checkpointer.adelete_thread(self.thread.id)
                else:
                    config["configurable"]["checkpoint_id"] = point.checkpoint_id
        return config, resolved_input

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
        the whole astream/ainvoke loop, opens the AsyncPostgresSaver, connects the
        run's sandbox and stages its skills, builds the LangGraph agent against the
        live tools, and resolves the request input and run config in one place.
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
            await self._open_sandbox()
            agent = self._build_agent(checkpointer, output_schema)
            resolved_input = self._resolve_input(agent_input, command)
            if self._sandbox is not None and self._sandbox.replaced:
                resolved_input = _with_host_notice(
                    resolved_input, SANDBOX_REPLACED_NOTICE, "sandbox_replaced"
                )
            config, resolved_input = await self._resolve_config(
                agent, checkpointer, trigger, config_overrides, resolved_input
            )
            yield agent, resolved_input, config

    async def _persist_sandbox(self) -> None:
        """Snapshot the sandbox state at turn end, if one was used.

        Cloud Run sandboxes live inside a single instance, so their overlay is
        exported to GCS here for cross-instance reconnects; OpenSandbox's
        persist is a no-op. Failures are logged, never raised — a snapshot
        problem must not mask the run's result.
        """
        if self._sandbox is None:
            return
        try:
            await asyncio.to_thread(self._sandbox.persist)
        except Exception:
            logger.exception("Failed to persist sandbox state")

    def _sandbox_for(self, resolved: ResolvedAgent):
        """The run's live sandbox, for an agent bound to one."""
        if self._sandbox is None or resolved.sandbox is None:
            return None
        return self._sandbox.backend

    async def _open_sandbox(self) -> None:
        """Connect (or create) the thread's sandbox and put the graph's skill
        files in it — before the graph runs, so the model only ever sees a
        live filesystem.

        One sandbox per run, shared by the parent and its subagents; the
        thread remembers its id so the next run reconnects to the same files.
        A sandbox that is gone and has no snapshot is replaced (and the model
        told, see `SANDBOX_REPLACED_NOTICE`); any other failure fails the run.

        The graph shares one skill set (merged in `build`), so it is
        materialized once under `SKILLS_ROOT`: a supervisor without code
        execution reads a skill from state and delegates its script to a
        sandboxed subagent by the same absolute path.
        """
        bound = [ra for ra in [self.agent, *self.subagents] if ra.sandbox is not None]
        if not bound:
            return
        provider = bound[0].sandbox.provider
        session = await asyncio.to_thread(
            open_sandbox, provider, self.thread.sandbox_id
        )
        if session.sandbox_id != self.thread.sandbox_id:
            await self._remember_sandbox(session.sandbox_id)
        await asyncio.to_thread(
            materialize_skills,
            session.backend,
            SKILLS_ROOT,
            skill_files(self.agent.skills, SKILLS_ROOT),
        )
        self._sandbox = session

    async def _remember_sandbox(self, sandbox_id: str) -> None:
        """Stamp the sandbox on the thread so the next run reconnects to it.

        Out-of-request: the worker's session is not ours to commit, so the
        stamp gets its own short transaction.
        """
        async with AsyncSessionLocal() as db:
            await ThreadRepository(db).set_sandbox_id(self.thread.id, sandbox_id)
            await db.commit()
        self.thread.sandbox_id = sandbox_id

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
        """Run one turn, yielding Agent Streaming Protocol events (`{method,
        params}` dicts — see `app/agents/protocol/emit.py`).

        The graph is driven through langgraph's `astream_events(version="v3")`,
        which emits the protocol grammar natively for every namespace
        (subagents included); `ProtocolEmitter` applies the publish-side
        policies the web client's contract needs. A graph failure propagates
        to the caller — the worker finalizes the run as `error` and publishes
        the terminal lifecycle with the root-cause message.

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
            # The call itself must be awaited; iterating the returned run
            # stream is what drives the graph (no background task). The
            # context manager aborts the graph iterator on an early exit —
            # the worker's cancel lands here as a CancelledError. `updates`
            # is opt-in: the emitter reads each node's written messages off
            # it to complete tool calls that never ran (see ProtocolEmitter).
            run = await agent.astream_events(
                stream_input,
                config=config,
                version="v3",
                transformers=[UpdatesTransformer],
            )
            emitter = ProtocolEmitter()
            try:
                async with run:
                    async for event in emitter.stream(run):
                        yield event
            except GraphRecursionError:
                ai_msg = await self._persist_recursion_fallback(agent, config)
                state = await agent.aget_state(config)
                for event in emitter.synthetic_ai_message(ai_msg, state.values):
                    yield event
            finally:
                await self._persist_sandbox()


SANDBOX_REPLACED_NOTICE = (
    "[Host notice] The sandbox used earlier in this conversation no longer "
    "exists and had no snapshot. A new, empty sandbox has been created: files "
    "written earlier are gone, so recreate anything you need before using it."
)


def _with_host_notice(resolved_input, text: str, kind: str):
    """Prepend a host-authored message to a turn's input so it lands in the
    checkpoint ahead of the user's message.

    The user role is the one channel every provider accepts mid-history and
    every harness uses for this (LangChain's summaries, OpenHands' environment
    events, Claude Code's reminders); `name`/`host_notice` let the chat render
    it as an event rather than as the user, and Slack skip it. A resume
    (`Command`) carries no messages to prepend to and is left alone.
    """
    if not isinstance(resolved_input, dict):
        return resolved_input
    notice = HumanMessage(
        content=text, name="host", additional_kwargs={"host_notice": kind}
    )
    return {**resolved_input, "messages": [notice, *resolved_input.get("messages", [])]}


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
        state = await get_checkpoint_state(checkpointer, thread_id)
    return extract_invoke_result(state.messages, state.structured_response)


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
