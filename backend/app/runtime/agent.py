import asyncio
import logging
from collections.abc import Sequence
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from deepagents.backends import StateBackend
from deepagents.backends.sandbox import BaseSandbox
from deepagents.graph import DeepAgentState
from deepagents.middleware._prompt_caching import append_prompt_caching_middleware
from deepagents.middleware.patch_tool_calls import PatchToolCallsMiddleware
from deepagents.middleware.subagents import CompiledSubAgent, SubAgentMiddleware
from langchain.agents import create_agent
from langchain.agents.middleware import (
    HumanInTheLoopMiddleware,
    ModelRetryMiddleware,
    ToolCallLimitMiddleware,
)
from langchain_core.exceptions import ModelError
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    convert_to_messages,
)
from langchain_core.tools import BaseTool
from langgraph.errors import GraphRecursionError
from langgraph.stream.transformers import UpdatesTransformer
from langgraph.types import Command
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.core.repository import AgentRepository
from app.agents.models import AgentMCPServerDB, ToolDiscoveryMode, ToolStatus
from app.agents.run_spec import AgentSpec, RunSpec
from app.artifacts.models import ArtifactDB
from app.artifacts.service import ATTACHMENTS_ROOT, ArtifactService
from app.artifacts.tool import present_files_tool
from app.database import AsyncSessionLocal, get_checkpointer
from app.exceptions import DomainValidationError, NotFoundError, PermissionDeniedError
from app.integrations.tracing import NoOpTracing, RunTracing, get_tracing
from app.memories.constants import MEMORY_STATE_KEY
from app.memories.middleware import MemoryMiddleware
from app.memories.repository import MemoryPreferenceRepository, MemoryRepository
from app.model_providers.catalog import ChatModelFactory
from app.model_providers.service import ModelService
from app.model_providers.web_search import (
    compatible_reasoning_effort,
    native_web_search_tool,
)
from app.observability.service import WorkspaceObservabilityService
from app.projects.runtime import (
    ProjectRunContext,
    resolve_project_run_context,
    upload_project_context,
)
from app.runtime.checkpoints import checkpoint_thread_id, get_checkpoint_state
from app.runtime.harness import (
    HARNESS_CONFIG,
    harness_middleware,
    harness_system_prompt,
    harness_trailing_middleware,
)
from app.runtime.middleware.current_date import CurrentDateMiddleware
from app.runtime.middleware.incomplete_response import IncompleteResponseMiddleware
from app.runtime.middleware.mcp_content import MCPContentCompatibilityMiddleware
from app.runtime.middleware.structured_output import (
    FORMAT_TOOL,
    PROVIDER_FORMAT_MODES,
    DeferredStructuredOutputMiddleware,
    is_structured_output_artifact,
)
from app.runtime.middleware.tool_errors import (
    RepairInvalidToolCallsMiddleware,
    ToolErrorMiddleware,
)
from app.runtime.middleware.tool_selection import (
    HIDDEN_SCHEMA_MODES,
    LOCAL_DISCOVERY_CANDIDATES_KEY,
    LOCAL_DISCOVERY_STATE_KEY,
    discovery_interrupt_on,
    tool_discovery_middleware,
)
from app.runtime.protocol.emit import ProtocolEmitter
from app.runtime.settings import agent_settings
from app.runtime.tool_catalog import ToolCatalog
from app.runtime.toolset import (
    MCPResolutionScope,
    PreparedToolset,
    Toolset,
    sanitize_tool_name,
)
from app.sandbox.provider import (
    BaseSandboxProvider,
    DeferredSandbox,
    SandboxSession,
    build_provider,
    open_sandbox,
)
from app.skills.middleware import read_only_files_middleware, skills_read_middleware
from app.skills.runtime import (
    SkillsBackend,
    resolve_run_skills,
    skill_files,
    upload_skills,
)
from app.skills.schemas import SkillBundle
from app.threads.models import ThreadDB, ThreadSource, ThreadToolMode
from app.threads.repository import ThreadRepository


logger = logging.getLogger(__name__)


RECURSION_LIMIT_MESSAGE = (
    "I reached my step limit for this turn. Send any follow-up message "
    '(e.g. "continue") and I\'ll pick up where I left off.'
)

SANDBOX_REPLACED_NOTICE = (
    "[Host notice] The sandbox used earlier in this conversation no longer "
    "exists and had no snapshot. A new, empty sandbox was created, then the "
    "files listed in a host notice were restored. Anything else written earlier "
    "is gone, so recreate what you need before using it."
)

ATTACHMENTS_PROMPT = (
    f"Files the user attaches to messages are placed in {ATTACHMENTS_ROOT}/ "
    "on the sandbox disk."
)


def with_attachments_prompt(instructions: str, sandboxed: bool) -> str:
    if not sandboxed:
        return instructions
    return f"{instructions}\n\n{ATTACHMENTS_PROMPT}".lstrip()


def _file_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB"):
        if value < 1024 or unit == "MB":
            return f"{int(value)} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    raise AssertionError


def files_notice(rows: list[ArtifactDB]) -> str:
    lines = [
        f"- {row.source_path} ({row.mime_type}, {_file_size(row.size)})" for row in rows
    ]
    return "[Host notice] Files are available on disk:\n" + "\n".join(lines)


def message_attachment_ids(messages: object) -> set[str]:
    if not isinstance(messages, list):
        return set()
    ids: set[str] = set()
    for message in messages:
        if isinstance(message, BaseMessage):
            additional_kwargs = message.additional_kwargs
        elif isinstance(message, dict):
            additional_kwargs = message.get("additional_kwargs")
        else:
            continue
        attachments = (
            additional_kwargs.get("attachments")
            if isinstance(additional_kwargs, dict)
            else None
        )
        if not isinstance(attachments, list):
            continue
        for attachment in attachments:
            value = (
                attachment
                if isinstance(attachment, str)
                else attachment.get("id")
                if isinstance(attachment, dict)
                else None
            )
            if isinstance(value, str):
                ids.add(value)
    return ids


def input_attachment_ids(agent_input: dict | None) -> set[str]:
    messages = agent_input.get("messages") if isinstance(agent_input, dict) else None
    return message_attachment_ids(messages)


@dataclass(frozen=True)
class RegenerationPoint:
    """Where a regeneration restarts the thread from, and with what.

    ``checkpoint_id`` is the checkpoint to fork from — the last one *before*
    the turn being redone. ``None`` means the turn being redone was the
    thread's first, so there is nothing earlier to fork from and the thread
    restarts from scratch instead. ``message`` is the user message that
    opened the turn, re-sent as the fork's input under its original id, and
    ``notices`` the host notices ahead of it, re-sent with it: the fork drops
    them, and the run that made them (e.g. placing the files) won't again.
    """

    checkpoint_id: str | None
    message: HumanMessage | None
    notices: tuple[HumanMessage, ...] = ()


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
        messages = latest.values.get("messages", [])
        at = next(
            (
                i
                for i in reversed(range(len(messages)))
                if isinstance(messages[i], HumanMessage)
            ),
            None,
        )
        message = None if at is None else messages[at]
        start = at or 0
        while start > 0 and _is_host_notice(messages[start - 1]):
            start -= 1
        notices = tuple(messages[start:at]) if at is not None else ()
        parent = state.parent_config
        return RegenerationPoint(
            checkpoint_id=parent["configurable"]["checkpoint_id"] if parent else None,
            message=message,
            notices=notices,
        )
    return None


def _append_system_prompt_context(system_prompt, context: str | None):
    if not context:
        return system_prompt
    if not system_prompt:
        return context
    if isinstance(system_prompt, SystemMessage):
        return SystemMessage(
            content_blocks=[
                *system_prompt.content_blocks,
                {"type": "text", "text": f"\n\n{context}"},
            ]
        )
    return f"{system_prompt}\n\n{context}"


def build_runnable(
    *,
    model,
    tools,
    system_prompt,
    mcp_context: str | None = None,
    sandbox_backend=None,
    skills: SkillsBackend | None = None,
    skills_enabled: bool = True,
    shared_context: str | None = None,
    base_middleware=(),
    subagents=None,
    checkpointer=None,
    output_schema: dict | None = None,
    format_mode: str = FORMAT_TOOL,
    tool_discovery_mode: ToolDiscoveryMode = ToolDiscoveryMode.disabled,
    router_model=None,
    server_descriptions: dict[str, str | None] | None = None,
    discoverable_tools=(),
    general_purpose_interrupt_on: dict[str, bool] | None = None,
    general_purpose_tools=None,
    artifact_context: tuple[UUID, str, UUID] | None = None,
):
    """Build a LangGraph runnable. One construction path, one middleware list.

    Every agent — parent or subagent, sandboxed or not — is a ``create_agent``
    with an explicit middleware stack, ending in prompt caching (a no-op off
    Anthropic). A sandbox adds deepagents' harness (todos, skills, filesystem,
    the ``task`` tool, summarization and the tool-call patcher) and appends the
    harness prompt to the agent's instructions; ``app/runtime/harness.py``
    assembles that bundle and ``tests/runtime/test_harness_parity.py`` pins it
    to what ``create_deep_agent`` builds. Nothing else forks on the sandbox.

    ``sandbox_backend`` has the sandbox interface but opens its provider only
    on the first filesystem or execution call. ``skills`` is the run's
    read-only ``SkillsBackend`` (None when the graph has no skills, which means
    no middleware and no prompt fragment, as in ``create_deep_agent``): the
    skill index is always read from it, and an agent without a sandbox also
    gets ``ls`` / ``read_file`` over it — its only filesystem, and no process
    anywhere.

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
    ``app.runtime.checkpoints.get_checkpoint_state``.
    """
    tools = list(tools)
    general_purpose_tools = (
        list(general_purpose_tools)
        if general_purpose_tools is not None
        else list(tools)
    )
    searchable_tools = list(discoverable_tools)
    if not isinstance(tool_discovery_mode, ToolDiscoveryMode):
        tool_discovery_mode = ToolDiscoveryMode.disabled
    private_state_keys = frozenset(
        {
            MEMORY_STATE_KEY,
            *(
                {
                    LOCAL_DISCOVERY_STATE_KEY,
                    LOCAL_DISCOVERY_CANDIDATES_KEY,
                }
                if tool_discovery_mode in HIDDEN_SCHEMA_MODES
                else set()
            ),
        }
    )
    catalog = (
        ToolCatalog(searchable_tools)
        if tool_discovery_mode is ToolDiscoveryMode.local and searchable_tools
        else None
    )
    system_prompt = _append_system_prompt_context(system_prompt, mcp_context)
    system_prompt = _append_system_prompt_context(system_prompt, shared_context)
    harness: list = []

    def discovery_for(agent_model):
        return tool_discovery_middleware(
            model=agent_model,
            searchable_tools=searchable_tools,
            mode=tool_discovery_mode,
            catalog=catalog,
            server_context=mcp_context,
            server_descriptions=server_descriptions,
            router_model=router_model,
        )

    if sandbox_backend is not None:
        if artifact_context is not None:
            present_tool = present_files_tool(sandbox_backend, *artifact_context)
            tools.append(present_tool)
            general_purpose_tools.append(present_tool)
        general_purpose_discovery = discovery_for(model)
        harness += harness_middleware(
            model=model,
            tools=tools,
            general_purpose_tools=general_purpose_tools,
            backend=sandbox_backend,
            subagents=subagents,
            skills=skills,
            skills_enabled=skills_enabled,
            mcp_context=mcp_context,
            shared_context=shared_context,
            general_purpose_middleware=(
                [general_purpose_discovery] if general_purpose_discovery else []
            ),
            general_purpose_interrupt_on=(
                discovery_interrupt_on(
                    general_purpose_interrupt_on, tool_discovery_mode
                )
            ),
            private_state_keys=private_state_keys,
        )
        system_prompt = harness_system_prompt(model, system_prompt)
        # The harness brings its own PatchToolCallsMiddleware and langchain
        # asserts against duplicates, so the caller's copy is dropped.
        base_middleware = [
            m for m in base_middleware if not isinstance(m, PatchToolCallsMiddleware)
        ]
    elif skills is not None and skills_enabled:
        harness += skills_read_middleware(skills)
    elif skills is not None:
        harness.append(read_only_files_middleware(skills))

    discovery = discovery_for(model)
    # Discovery wraps the harness so hidden schemas are removed before
    # summarization counts the request.
    middleware = [
        MCPContentCompatibilityMiddleware(),
        *([discovery] if discovery is not None else []),
        *harness,
        *base_middleware,
    ]
    if sandbox_backend is None and subagents:
        # On the far side of the caller's stack, where the plain path has
        # always put it — the harness wires its own SubAgentMiddleware *before*
        # the caller's, because that is where deepagents puts it. Since
        # deepagents 0.7 the middleware injects no system-prompt fragment of
        # its own (the `task` tool description carries the agent list), so the
        # position only orders hooks now.
        middleware.append(
            SubAgentMiddleware(
                backend=StateBackend(),
                subagents=subagents,
                private_state_keys=private_state_keys,
            )
        )
    if output_schema is not None:
        middleware.append(DeferredStructuredOutputMiddleware(format_mode))
    middleware.append(ToolErrorMiddleware())
    if sandbox_backend is not None:
        middleware += harness_trailing_middleware(model)
    else:
        append_prompt_caching_middleware(middleware)

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


def _retry_model_call(exc: Exception) -> bool:
    """Retry transport/provider failures, not deterministic local conversion."""
    if isinstance(exc, ModelError):
        return exc.is_retryable
    return not isinstance(exc, (KeyError, TypeError, ValueError))


def build_agent_middleware(
    created_at: datetime,
    *,
    recursion_limit: int,
    interrupt_on: dict[str, bool] | None = None,
    tool_discovery_mode: ToolDiscoveryMode = ToolDiscoveryMode.disabled,
) -> list:
    """The middleware stack every agent gets, parent or subagent.

    Order is load-bearing. PatchToolCallsMiddleware runs first so that any
    dangling tool_calls left by a previous aborted turn (recursion limit,
    cancelled stream, etc.) get synthetic ToolMessage responses before the model
    sees them. ModelRetryMiddleware is listed early so a retry re-runs the whole
    inner pipeline (date stamp, deferred formatting); it retries transient model
    failures (rate limits, timeouts, connection drops — classified via
    ``ModelError.is_retryable``) and, when retries are exhausted, persists the
    failure as a durable run error. Non-retryable errors (e.g. provider 400s)
    re-raise immediately and surface through the run record.
    RepairInvalidToolCallsMiddleware is placed *before*
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
    into it — see ``app/runtime/hitl.py``. Only tests and the structured-output
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
    resolved_interrupt_on = discovery_interrupt_on(interrupt_on, tool_discovery_mode)
    return [
        *([PatchToolCallsMiddleware()] if checkpointed else []),
        ModelRetryMiddleware(retry_on=_retry_model_call, on_failure="error"),
        ToolCallLimitMiddleware(
            run_limit=(recursion_limit - 1) // 2, exit_behavior="end"
        ),
        IncompleteResponseMiddleware(),
        RepairInvalidToolCallsMiddleware(),
        *(
            [
                HumanInTheLoopMiddleware(
                    interrupt_on=resolved_interrupt_on,
                    description_prefix="Tool execution pending approval",
                )
            ]
            if checkpointed
            else []
        ),
        CurrentDateMiddleware(created_at),
    ]


def build_parent_middleware(
    created_at: datetime,
    prepared: PreparedToolset,
    tool_discovery_mode: ToolDiscoveryMode = ToolDiscoveryMode.disabled,
    runtime_tool_interrupt_on: dict[str, bool] | None = None,
) -> list:
    """The parent agent's stack: checkpointed, under our own recursion limit."""
    interrupt_on = {
        **prepared.interrupt_on,
        **(runtime_tool_interrupt_on or {}),
    }
    return build_agent_middleware(
        created_at,
        recursion_limit=agent_settings.recursion_limit,
        interrupt_on=interrupt_on,
        tool_discovery_mode=tool_discovery_mode,
    )


@dataclass
class ResolvedSandbox:
    """An agent's sandbox binding, resolved to a ready provider: the row is
    loaded and its credential decrypted at request scope, so the streaming
    scope (and subagent compile) never touch the DB or a global."""

    provider: BaseSandboxProvider
    tools: dict | None
    # The sandbox row this provider was built from: the thread stores it
    # alongside the sandbox id, so a later run can tell whether the id it
    # remembers was issued by *this* sandbox or a previous binding.
    row_id: UUID | None = None


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
            spec.mcp_servers,
            db,
            user_id,
            spec.workspace_id,
            apply_ui=is_parent,
            scope=scope,
        )
        return cls(config=spec, prepared=prepared, sandbox=cls._resolve_sandbox(spec))

    @staticmethod
    def _resolve_sandbox(spec: AgentSpec) -> ResolvedSandbox | None:
        if spec.sandbox is None:
            return None
        # A row that no longer validates (e.g. secret cleared) raises
        # `SandboxUnavailableError` and fails the run — the pre-run gate
        # reports the same, so this only covers a change made in between.
        # Silently running without code execution would be worse.
        provider = build_provider(spec.sandbox.row)
        return ResolvedSandbox(
            provider=provider,
            tools=spec.sandbox.tools,
            row_id=spec.sandbox.row.id,
        )

    def compile(
        self,
        model,
        created_at: datetime,
        *,
        sandbox_backend=None,
        skills: SkillsBackend | None = None,
        skills_enabled: bool = True,
        shared_context: str | None = None,
        web_search_tool: dict | None = None,
        router_model=None,
        artifact_context: tuple[UUID, str, UUID] | None = None,
    ) -> CompiledSubAgent:
        """Compile into a CompiledSubAgent runnable (for subagent use).

        ``created_at`` is the thread's creation date, stamped onto the
        subagent's system prompt by ``CurrentDateMiddleware``.
        ``sandbox_backend`` is the run's one live sandbox, handed over when
        this subagent is bound to a sandbox; ``skills`` the run's shared set.

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
        # A subagent bound to a sandbox shares the run's one live sandbox, so
        # the parent's turn-end persist covers what it wrote (issue #302).
        runnable = build_runnable(
            model=model,
            tools=[
                *self.live.all,
                *([web_search_tool] if web_search_tool is not None else []),
            ],
            system_prompt=with_attachments_prompt(
                self.config.instructions or "",
                sandbox_backend is not None and self.sandbox is not None,
            ),
            mcp_context=self.prepared.mcp_context_prompt,
            sandbox_backend=sandbox_backend if self.sandbox else None,
            skills=skills,
            skills_enabled=skills_enabled,
            shared_context=shared_context,
            base_middleware=build_agent_middleware(
                created_at,
                recursion_limit=agent_settings.recursion_limit,
                interrupt_on=self.prepared.interrupt_on,
                tool_discovery_mode=self.config.tool_discovery_mode,
            ),
            tool_discovery_mode=self.config.tool_discovery_mode,
            router_model=router_model,
            server_descriptions=self.prepared.server_description_by_name,
            discoverable_tools=self.live.all,
            general_purpose_interrupt_on=self.prepared.interrupt_on,
            artifact_context=artifact_context,
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
        subagents: list[ResolvedAgent],
        provider: str | None = None,
        web_search_supported: bool = False,
        router_model=None,
        skills: list[SkillBundle] = (),
        project_context: ProjectRunContext | None = None,
        tracing: RunTracing | None = None,
        runtime_tools: Sequence[BaseTool] = (),
        runtime_tool_interrupt_on: dict[str, bool] | None = None,
    ):
        self.thread = thread
        self.agent = agent
        self.model = model
        self.middleware = middleware
        self.tracing = tracing if tracing is not None else NoOpTracing()
        self.subagents = subagents
        self.provider = provider
        self.web_search_supported = web_search_supported
        # Minimal-effort variant of `model` for the lazy MCP router; None when
        # no agent of the graph runs lazy discovery.
        self.router_model = router_model
        # Run-bound tools are supplied by integrations, not persisted on the
        # agent and never included in MCP discovery.
        self.runtime_tools = list(runtime_tools)
        self.runtime_tool_interrupt_on = dict(runtime_tool_interrupt_on or {})
        # One skill set for the whole graph, frozen for this run.
        self.skills = list(skills)
        self.project_context = project_context
        # The provider session exists only after the model first uses a sandbox
        # tool (or immediately when this turn attaches files).
        self._sandbox: SandboxSession | None = None
        self._sandbox_backend: DeferredSandbox | None = None
        # Files restored or attached to this turn and announced to the model.
        self._announced_files: list[ArtifactDB] = []

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
            "configurable": {
                "thread_id": checkpoint_thread_id(
                    self.thread.workspace_id, self.thread.id
                )
            },
            "recursion_limit": agent_settings.recursion_limit,
            "callbacks": self.tracing.callbacks,
            "metadata": self.metadata,
        }

    @classmethod
    async def build(
        cls,
        thread: ThreadDB,
        db: AsyncSession,
        *,
        runtime_tools: Sequence[BaseTool] = (),
        runtime_tool_interrupt_on: dict[str, bool] | None = None,
    ) -> "Agent":
        """Resolve everything a run needs from the database.

        A resume (a HITL approval) resolves exactly as a first run does —
        there is no per-thread copy of anything to reuse.
        """
        user_id = str(thread.user_id)

        # One read for the whole graph. This used to be a full `AgentService.get`
        # per agent, run sequentially for subagents (§1.2): ~8 + 7N round-trips
        # before the first token.
        spec = await AgentRepository(db, thread.workspace_id).get_run_spec(
            thread.agent_id
        )
        if spec is None:
            raise NotFoundError("Agent not found")
        project_context = await resolve_project_run_context(
            db,
            thread.workspace_id,
            thread.project_id,
            thread.user_id,
        )
        if thread.project_id is not None and project_context is None:
            raise PermissionDeniedError(
                "Thread owner can no longer access this project"
            )

        # The thread is the runtime source of truth on every surface. Slack and
        # Telegram stamp their connection default when they create a thread;
        # later web edits therefore apply to subsequent side-channel turns.
        discovery_override = {
            ThreadToolMode.eager: ToolDiscoveryMode.disabled,
            ThreadToolMode.lazy: ToolDiscoveryMode.lazy,
            ThreadToolMode.precision: ToolDiscoveryMode.local,
            ThreadToolMode.force_all: ToolDiscoveryMode.disabled,
        }.get(thread.tool_mode)
        force_no_tools = thread.tool_mode is ThreadToolMode.no_tools
        lazy_overrides_resource_selections = (
            discovery_override is ToolDiscoveryMode.lazy
            or (
                discovery_override is None
                and spec.agent.tool_discovery_mode is ToolDiscoveryMode.lazy
            )
        )
        force_enable_resources = (
            thread.tool_mode is not None
            and thread.tool_mode.force_enable_all_capabilities
        ) or lazy_overrides_resource_selections
        exclusions = spec.resource_exclusions(
            disabled_mcp_server_ids={
                UUID(server_id) for server_id in thread.disabled_mcp_server_ids
            },
            disabled_sandbox_ids={
                UUID(sandbox_id) for sandbox_id in thread.disabled_sandbox_ids
            },
            disabled_subagent_ids={
                UUID(subagent_id) for subagent_id in thread.disabled_subagent_ids
            },
            force_enable_all_capabilities=True if force_enable_resources else None,
            force_disable_all_capabilities=force_no_tools,
        )

        def filter_resources(agent_spec: AgentSpec) -> AgentSpec:
            def configure_binding(binding: AgentMCPServerDB) -> AgentMCPServerDB:
                if thread.source != ThreadSource.trigger:
                    return binding
                rejected = set(
                    thread.disabled_mcp_tools.get(str(binding.mcp_server_id), [])
                )
                return binding.model_copy(
                    update={
                        "tools": {
                            name: (
                                ToolStatus.disabled
                                if status == ToolStatus.disabled or name in rejected
                                else ToolStatus.always_allow
                            )
                            for name, status in (binding.tools or {}).items()
                        }
                    }
                )

            return replace(
                agent_spec,
                mcp_servers=[
                    configure_binding(binding)
                    for binding in agent_spec.mcp_servers
                    if binding.mcp_server_id not in exclusions.mcp_server_ids
                ],
                sandbox=(
                    None
                    if agent_spec.sandbox is not None
                    and agent_spec.sandbox.row.id in exclusions.sandbox_ids
                    else agent_spec.sandbox
                ),
                tool_discovery_mode=(
                    discovery_override
                    if discovery_override is not None
                    else agent_spec.tool_discovery_mode
                ),
                web_search_enabled=(
                    False if force_no_tools else agent_spec.web_search_enabled
                ),
            )

        spec = RunSpec(
            agent=filter_resources(spec.agent),
            subagents=[
                filter_resources(subagent)
                for subagent in spec.subagents
                if subagent.id not in exclusions.subagent_ids
            ],
        )

        # Every MCP server the graph touches, in one query — the parent's and
        # each subagent's (design review §2.2 / P2-6).
        scope = await MCPResolutionScope.build(
            spec.all_mcp_bindings,
            db,
            user_id,
            thread.workspace_id,
            authorized_only=True,
        )
        agent = await ResolvedAgent.resolve(
            spec.agent, db, user_id, is_parent=True, scope=scope
        )

        # Backstop for the RunService.create gate: covers the race where the
        # model is disabled between enqueue and worker pickup, and any future
        # path that builds an agent without going through `create`.
        resolved = await ModelService(db, thread.workspace_id).ensure_available(
            thread.model_id, reasoning_effort=thread.reasoning_effort
        )
        web_search_enabled = (
            not force_no_tools
            and resolved.supports_web_search
            and any(item.web_search_enabled for item in [spec.agent, *spec.subagents])
        )
        reasoning_effort = compatible_reasoning_effort(
            resolved.provider,
            resolved.reasoning_effort,
            web_search_enabled=web_search_enabled,
        )
        if reasoning_effort != resolved.reasoning_effort:
            logger.info(
                "Adjusted reasoning effort from %s to %s for model %s because "
                "native web search is enabled",
                resolved.reasoning_effort,
                reasoning_effort,
                resolved.model_id,
            )
        model = ChatModelFactory().create(
            resolved.provider,
            resolved.runtime_model_id,
            resolved.api_key,
            reasoning_effort=reasoning_effort,
            base_url=resolved.base_url,
        )
        # The lazy MCP router is one tiny call per prompt. It runs on the
        # workspace quick model when an admin flagged one; otherwise on the
        # thread's model at its least declared effort, so it answers fast.
        # Reuse `model` when that is where the run already sits.
        router_model = None
        if any(
            item.tool_discovery_mode is ToolDiscoveryMode.lazy
            for item in [spec.agent, *spec.subagents]
        ):
            quick = await ModelService(db, thread.workspace_id).resolve_quick()
            if quick is not None:
                router_model = ChatModelFactory().create(
                    quick.provider,
                    quick.runtime_model_id,
                    quick.api_key,
                    reasoning_effort=quick.minimal_reasoning_effort,
                    base_url=quick.base_url,
                )
            else:
                minimal_effort = compatible_reasoning_effort(
                    resolved.provider,
                    resolved.minimal_reasoning_effort,
                    web_search_enabled=web_search_enabled,
                )
                router_model = (
                    model
                    if minimal_effort == reasoning_effort
                    else ChatModelFactory().create(
                        resolved.provider,
                        resolved.runtime_model_id,
                        resolved.api_key,
                        reasoning_effort=minimal_effort,
                        base_url=resolved.base_url,
                    )
                )

        middleware = build_parent_middleware(
            thread.created_at,
            agent.prepared,
            agent.config.tool_discovery_mode,
            runtime_tool_interrupt_on,
        )
        if thread.memories_enabled:
            preference = await MemoryPreferenceRepository(db).get_for_user(
                thread.user_id
            )
            memory_rows = await MemoryRepository(db).list_recent_for_user(
                thread.user_id, limit=200
            )
            middleware.append(
                MemoryMiddleware(
                    user_id=thread.user_id,
                    workspace_id=thread.workspace_id,
                    thread_id=thread.id,
                    rows=memory_rows,
                    auto_capture_enabled=(
                        preference.auto_capture_enabled
                        if preference is not None
                        else False
                    ),
                    tools_enabled=not force_no_tools,
                )
            )

        # Still sequential, and deliberately so: these share one AsyncSession,
        # which is not concurrency-safe. It no longer costs anything to be —
        # `get_run_spec` read the agent rows and `scope` the MCP ones, so each
        # resolve is Redis/CPU work over rows already in hand.
        subagents = [
            await ResolvedAgent.resolve(sub, db, user_id, scope=scope)
            for sub in spec.subagents
        ]

        # One skill set per graph: every agent lists, reads and runs the union
        # of what the supervisor and its subagents have enabled.
        disabled_skill_ids = {UUID(skill_id) for skill_id in thread.disabled_skill_ids}
        skills = (
            []
            if force_no_tools
            else await resolve_run_skills(
                db,
                spec.all_agent_ids,
                thread.workspace_id,
                project_skill_ids=(
                    project_context.skill_ids if project_context is not None else ()
                ),
                excluded_skill_ids=disabled_skill_ids,
            )
        )
        try:
            observability = await WorkspaceObservabilityService(db).get_runtime_config(
                thread.workspace_id
            )
        except Exception:  # noqa: BLE001 — optional tracing must never block a run
            logger.warning(
                "Could not load observability settings; continuing without tracing",
                exc_info=True,
            )
            observability = None

        return cls(
            thread=thread,
            agent=agent,
            model=model,
            middleware=middleware,
            tracing=get_tracing(observability),
            subagents=subagents,
            provider=resolved.provider,
            web_search_supported=resolved.supports_web_search,
            router_model=router_model,
            skills=skills,
            project_context=project_context,
            runtime_tools=runtime_tools,
            runtime_tool_interrupt_on=runtime_tool_interrupt_on,
        )

    def _web_search_tool(self, agent: ResolvedAgent) -> dict | None:
        if (
            not agent.config.web_search_enabled
            or not self.web_search_supported
            or self.provider is None
        ):
            return None
        return native_web_search_tool(self.provider)

    def _build_agent(self, checkpointer, output_schema: dict | None = None):
        """Build the LangGraph agent (deep or standard) with the given checkpointer.

        `output_schema` is a raw JSON Schema dict passed to langchain as
        `response_format`. DeferredStructuredOutputMiddleware keeps the schema
        off the tool-calling loop and applies it on one final formatting turn;
        the parsed result surfaces in the run state under `structured_response`.
        """
        # Read-only and shared by every agent of the graph; None means no
        # skills middleware and no prompt fragment at all.
        project_files = (
            self.project_context.files if self.project_context is not None else {}
        )
        skills = (
            SkillsBackend(self.skills, project_files)
            if self.skills or project_files
            else None
        )
        shared_context = (
            self.project_context.system_context
            if self.project_context is not None
            else None
        )
        source = self._sandbox_binding()
        source_id = (
            self.thread.sandbox_source_id
            if self.thread.sandbox_source_id is not None
            else source.row_id
            if source is not None
            else None
        )
        artifact_context = (
            (self.thread.workspace_id, self.thread.id, source_id)
            if self._sandbox_backend is not None and source_id is not None
            else None
        )
        compiled = (
            [
                s.compile(
                    self.model,
                    self.thread.created_at,
                    sandbox_backend=self._sandbox_for(s),
                    skills=skills,
                    skills_enabled=bool(self.skills),
                    shared_context=shared_context,
                    web_search_tool=self._web_search_tool(s),
                    router_model=self.router_model,
                    artifact_context=artifact_context,
                )
                for s in self.subagents
            ]
            if self.subagents
            else None
        )
        sandbox_backend = self._sandbox_for(self.agent)
        web_search_tool = self._web_search_tool(self.agent)
        general_purpose_tools = [
            *self.agent.live.all,
            *([web_search_tool] if web_search_tool is not None else []),
        ]
        return build_runnable(
            model=self.model,
            tools=[
                *self.runtime_tools,
                *general_purpose_tools,
            ],
            system_prompt=with_attachments_prompt(
                self.agent.config.instructions or "", sandbox_backend is not None
            ),
            mcp_context=self.agent.prepared.mcp_context_prompt,
            sandbox_backend=sandbox_backend,
            skills=skills,
            skills_enabled=bool(self.skills),
            shared_context=shared_context,
            base_middleware=self.middleware,
            subagents=compiled,
            checkpointer=checkpointer,
            output_schema=output_schema,
            format_mode=PROVIDER_FORMAT_MODES.get(self.provider, FORMAT_TOOL),
            tool_discovery_mode=self.agent.config.tool_discovery_mode,
            router_model=self.router_model,
            server_descriptions=self.agent.prepared.server_description_by_name,
            discoverable_tools=self.agent.live.all,
            general_purpose_interrupt_on=self.agent.prepared.interrupt_on,
            general_purpose_tools=general_purpose_tools,
            artifact_context=artifact_context,
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
        for message in messages:
            # The host-notice marker is the runtime's own; a client cannot claim it.
            message.additional_kwargs.pop("host_notice", None)
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
                resolved_input = {
                    **resolved_input,
                    "messages": [*point.notices, *resolved_input["messages"]],
                }
                if point.checkpoint_id is None:
                    await checkpointer.adelete_thread(
                        checkpoint_thread_id(self.thread.workspace_id, self.thread.id)
                    )
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

        Scaffolding for `stream`: opens one persistent MCP session per server
        (parent + subagents) on an AsyncExitStack that lives for the whole
        astream/ainvoke loop, opens the AsyncPostgresSaver, installs a deferred
        sandbox backend, builds the LangGraph agent against the live tools, and
        resolves the request input and run config in one place.
        """
        async with AsyncExitStack() as stack, get_checkpointer() as checkpointer:
            stack.enter_context(
                self.tracing.run_context(
                    session_id=str(self.thread.id), user_id=str(self.thread.user_id)
                )
            )
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
            attachment_ids = input_attachment_ids(agent_input)
            source = self._sandbox_binding()
            if source is not None:
                self._sandbox_backend = DeferredSandbox(
                    lambda: self._open_sandbox(checkpointer, attachment_ids),
                    existing_id=self.thread.sandbox_id,
                )
                # Attachments must exist before the first model call because the
                # input includes a host notice naming their sandbox paths.
                if attachment_ids:
                    await self._open_sandbox(checkpointer, attachment_ids)
            agent = self._build_agent(checkpointer, output_schema)
            resolved_input = self._resolve_input(agent_input, command)
            config, resolved_input = await self._resolve_config(
                agent, checkpointer, trigger, config_overrides, resolved_input
            )
            if self._announced_files:
                resolved_input = _with_host_notice(
                    resolved_input,
                    files_notice(self._announced_files),
                    "files_restored",
                )
            if self._sandbox is not None and self._sandbox.replaced:
                resolved_input = _with_host_notice(
                    resolved_input, SANDBOX_REPLACED_NOTICE, "sandbox_replaced"
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
        """The run's deferred sandbox backend, for an agent bound to one."""
        if resolved.sandbox is None:
            return None
        if self._sandbox_backend is not None:
            return self._sandbox_backend
        return self._sandbox.backend if self._sandbox is not None else None

    def _sandbox_binding(self) -> ResolvedSandbox | None:
        return next(
            (
                resolved.sandbox
                for resolved in [self.agent, *self.subagents]
                if resolved.sandbox is not None
            ),
            None,
        )

    async def _open_sandbox(
        self, checkpointer, current_attachment_ids: set[str] | None = None
    ) -> BaseSandbox:
        """Connect (or create) the thread's sandbox and put the run's skill
        files on it when the graph first touches its filesystem.

        One sandbox per run, shared by the parent and every sandbox-bound
        subagent (the first bound member's provider); the thread remembers its
        id so the next run reconnects to the same files. A sandbox that is
        gone is replaced and the model told (`SANDBOX_REPLACED_NOTICE`); any
        other failure fails the run as `SandboxUnavailableError`. Provider
        calls are blocking SDK calls, run off the loop.
        """
        if self._sandbox is not None:
            return self._sandbox.backend
        source = self._sandbox_binding()
        if source is None:
            raise RuntimeError("Cannot open a sandbox for an unbound agent")
        # Only reconnect to an id this sandbox row issued. After a rebinding
        # the stored id belongs to the previous provider, which cannot know
        # it — reconnect failed the run instead of starting a fresh sandbox.
        # Reconnect only to an id this sandbox row issued. A null source means
        # the thread was stamped before that column existed — still this
        # sandbox, as far as anything knows, so it reconnects. Deleting a
        # sandbox row clears the thread's stamp outright (`SandboxService`),
        # so null never means "the issuer was deleted".
        previous = (
            self.thread.sandbox_id
            if self.thread.sandbox_source_id in (None, source.row_id)
            else None
        )
        session = await asyncio.to_thread(open_sandbox, source.provider, previous)
        # Also stamp legacy threads on reconnect: artifact publication requires
        # the workspace sandbox row that issued the provider sandbox id.
        if session.sandbox_id != self.thread.sandbox_id or (
            self.thread.sandbox_source_id is None and source.row_id is not None
        ):
            await self._remember_sandbox(session.sandbox_id, source.row_id)
        await asyncio.to_thread(
            upload_skills, session.backend, skill_files(self.skills)
        )
        await asyncio.to_thread(
            upload_project_context,
            session.backend,
            self.project_context.files if self.project_context is not None else {},
        )
        state = await get_checkpoint_state(
            checkpointer,
            checkpoint_thread_id(self.thread.workspace_id, self.thread.id),
        )
        visible_attachment_ids = set(current_attachment_ids or ())
        visible_attachment_ids.update(message_attachment_ids(state.messages))
        async with AsyncSessionLocal() as db:
            self._announced_files = await ArtifactService(
                db, self.thread.workspace_id
            ).restore(
                self.thread.id,
                session.backend,
                source.row_id,
                current_attachment_ids=current_attachment_ids,
                visible_attachment_ids=visible_attachment_ids,
            )
            await db.commit()
        self._sandbox = session
        return session.backend

    async def _remember_sandbox(self, sandbox_id: str, source_id) -> None:
        """Stamp the sandbox on the thread so the next run reconnects to it.

        Out-of-request, and outside the worker's session (which `_setup` does
        not have): the stamp gets its own short transaction, so it is written
        even if the run then fails.
        """
        async with AsyncSessionLocal() as db:
            await ThreadRepository(db, self.thread.workspace_id).set_sandbox_id(
                self.thread.id, sandbox_id, source_id
            )
            await db.commit()
        self.thread.sandbox_id = sandbox_id
        self.thread.sandbox_source_id = source_id

    async def _persist_recursion_fallback(self, agent, config) -> AIMessage:
        """Persist a synthetic AI message after a GraphRecursionError so the
        next turn can pick up where we left off. Returns the message."""
        logger.info("Graph recursion limit reached; persisting synthetic AI message")
        ai_msg = AIMessage(content=RECURSION_LIMIT_MESSAGE, id=str(uuid4()))
        await agent.aupdate_state(config, {"messages": [ai_msg]})
        return ai_msg

    async def _persist_interrupted_answer(
        self, agent, config, emitter: ProtocolEmitter
    ) -> None:
        """Persist the visible part of an interrupted root answer.

        The graph may already have checkpointed the completed message before
        cancellation lands, so deduplicate by id. Persistence failures are
        logged without masking the cancellation that stopped the run.
        """
        message = emitter.streamed_answer()
        if message is None:
            return
        try:
            state = await agent.aget_state(config)
            if any(item.id == message.id for item in state.values.get("messages", [])):
                return
            await agent.aupdate_state(config, {"messages": [message]})
        except Exception:
            logger.exception(
                "Could not save the interrupted answer of %s", self.thread.id
            )

    async def stream(
        self,
        agent_input: dict | None = None,
        command: dict | None = None,
        trigger: str | None = None,
        config_overrides: dict | None = None,
        output_schema: dict | None = None,
    ):
        """Run one turn, yielding Agent Streaming Protocol events (`{method,
        params}` dicts — see `app/runtime/protocol/emit.py`).

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
            except (asyncio.CancelledError, GeneratorExit):
                # Cancellation can arrive in this generator directly or as
                # `aclose()` when the worker is cancelled while publishing.
                await asyncio.shield(
                    self._persist_interrupted_answer(agent, config, emitter)
                )
                raise
            except GraphRecursionError:
                ai_msg = await self._persist_recursion_fallback(agent, config)
                state = await agent.aget_state(config)
                for event in emitter.synthetic_ai_message(ai_msg, state.values):
                    yield event
            finally:
                await self._persist_sandbox()


def _with_host_notice(resolved_input, text: str, kind: str):
    """Prepend a host-authored message to a turn's input so it lands in the
    checkpoint ahead of the user's message.

    The user role is the one channel every provider accepts mid-history and
    every harness uses for this (LangChain's summaries, OpenHands' environment
    events, Claude Code's reminders); `name`/`host_notice` let clients hide it
    while Slack skips it. A resume
    (`Command`) carries no messages to prepend to and is left alone.
    """
    if not isinstance(resolved_input, dict):
        return resolved_input
    notice = HumanMessage(
        content=text, name="host", additional_kwargs={"host_notice": kind}
    )
    # A regeneration may carry the redone turn's notice of this kind: this one is current.
    rest = [
        message
        for message in resolved_input.get("messages", [])
        if not (
            _is_host_notice(message)
            and message.additional_kwargs["host_notice"] == kind
        )
    ]
    return {**resolved_input, "messages": [notice, *rest]}


def _is_host_notice(message) -> bool:
    return (
        isinstance(message, HumanMessage)
        and message.name == "host"
        and "host_notice" in message.additional_kwargs
    )


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


async def read_run_result(workspace_id: UUID, thread_id: str) -> dict:
    """Read a thread's final-turn result from its checkpoint (out-of-request).

    The durable runtime streams a run to its event log rather than returning a
    value, so the synchronous `/runs/invoke` consumer reads the answer back from
    the LangGraph checkpoint once the run is terminal.
    """
    async with get_checkpointer() as checkpointer:
        state = await get_checkpoint_state(
            checkpointer, checkpoint_thread_id(workspace_id, thread_id)
        )
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
